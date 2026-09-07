package aegis

import (
	"context"
	"fmt"
	"math"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/klog/v2"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

// AegisPlugin implements the Kubernetes Scheduling Framework Plugins.
type AegisPlugin struct {
	handle framework.Handle
	config AegisPluginConfig
	cache  *PredictionCache
}

// var _ framework.FilterPlugin = &AegisPlugin{}
// var _ framework.ScorePlugin = &AegisPlugin{}

// Name returns the name of the plugin.
func (pl *AegisPlugin) Name() string {
	return Name
}

// New initializes a new plugin and returns it.
func New(obj runtime.Object, handle framework.Handle) (framework.Plugin, error) {
	// TODO: Parse config from obj
	cfg := DefaultConfig()

	cache := NewPredictionCache(cfg.PredictionTTL)
	cache.StartBackgroundUpdater(cfg.PredictorURL, cfg.PredictionTTL/2)

	return &AegisPlugin{
		handle: handle,
		config: cfg,
		cache:  cache,
	}, nil
}

// Filter checks if the node has enough predicted capacity.
func (pl *AegisPlugin) Filter(ctx context.Context, state *framework.CycleState, pod *v1.Pod, nodeInfo *framework.NodeInfo) *framework.Status {
	node := nodeInfo.Node()
	if node == nil {
		return framework.NewStatus(framework.Error, "node not found")
	}

	pred, exists := pl.cache.GetPrediction(node.Name)
	if !exists {
		// Fallback: pass filter safely if prediction is unavailable
		klog.V(4).Infof("Prediction unavailable for node %s, passing filter.", node.Name)
		return framework.NewStatus(framework.Success, "")
	}

	// Assuming pod requests some CPU/Mem. For stub, we just check max util threshold.
	// In full implementation, we'd add pod's requested resources to predicted util.
	if pred.PredictedCPU > pl.config.MaxUtilThreshold {
		return framework.NewStatus(framework.Unschedulable, "node predicted to exceed max utilization threshold")
	}

	return framework.NewStatus(framework.Success, "")
}

// Score computes the score for the node based on predicted util, energy cost, and balance.
func (pl *AegisPlugin) Score(ctx context.Context, state *framework.CycleState, pod *v1.Pod, nodeName string) (int64, *framework.Status) {
	pred, exists := pl.cache.GetPrediction(nodeName)
	if !exists {
		// Fallback score
		return pl.config.FallbackScore, framework.NewStatus(framework.Success, "")
	}

	// Formula: score = w1*(1 - predictedUtil) + w2*(-normalizedEnergyCost) + w3*balancePenalty
	
	// Util Component (0-1)
	utilScore := 1.0 - pred.PredictedCPU

	// Energy Component
	powerProfile := GetNodePowerProfile(nodeName)
	estimatedPower := ComputePower(pred.PredictedCPU, powerProfile)
	
	// To truly normalize across nodes, Score should return raw and NormalizeScore normalizes.
	// We'll calculate a local normalized value just for combining here, or pass raw values.
	// Let's pass a raw combined float via state if we wanted, but Score returns an int64.
	// We'll approximate a 0-100 score directly.

	// Inverted energy cost: lower energy is better
	energyScore := 1.0 - NormalizePowerCost(estimatedPower, powerProfile.PIdle, powerProfile.PMax)
	
	// Balance penalty (stubbed as 1.0 for now)
	balanceScore := 1.0

	// Combine scores
	rawScore := (pl.config.WeightUtil*utilScore + pl.config.WeightEnergy*energyScore + pl.config.WeightBalance*balanceScore)
	
	// Scale to 0-100
	totalWeights := pl.config.WeightUtil + pl.config.WeightEnergy + pl.config.WeightBalance
	finalScore := int64((rawScore / totalWeights) * 100)

	if finalScore > 100 {
		finalScore = 100
	} else if finalScore < 0 {
		finalScore = 0
	}

	return finalScore, framework.NewStatus(framework.Success, "")
}

// NormalizeScore normalizes scores across all nodes.
// Here we might just scale them to the framework.MaxNodeScore range (0-100).
func (pl *AegisPlugin) NormalizeScore(ctx context.Context, state *framework.CycleState, pod *v1.Pod, scores framework.NodeScoreList) *framework.Status {
	// Find min and max
	var min, max int64 = math.MaxInt64, -math.MaxInt64
	for _, score := range scores {
		if score.Score < min {
			min = score.Score
		}
		if score.Score > max {
			max = score.Score
		}
	}

	if max == min {
		for i := range scores {
			scores[i].Score = framework.MaxNodeScore
		}
		return framework.NewStatus(framework.Success, "")
	}

	// Normalize between 0 and framework.MaxNodeScore
	for i := range scores {
		val := float64(scores[i].Score-min) / float64(max-min)
		scores[i].Score = int64(val * float64(framework.MaxNodeScore))
	}

	return framework.NewStatus(framework.Success, "")
}

// ScoreExtensions returns the ScoreExtensions interface.
func (pl *AegisPlugin) ScoreExtensions() framework.ScoreExtensions {
	return pl
}
