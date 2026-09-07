package aegis

import (
	"context"
	"testing"
	"time"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

func TestScoreCalculation(t *testing.T) {
	// Setup
	cfg := DefaultConfig()
	cache := NewPredictionCache(cfg.PredictionTTL)
	
	cache.UpdatePredictions(map[string]*NodePrediction{
		"node1": {
			NodeName:     "node1",
			PredictedCPU: 0.2, // Low util
			Timestamp:    time.Now(),
		},
		"node2": {
			NodeName:     "node2",
			PredictedCPU: 0.9, // High util
			Timestamp:    time.Now(),
		},
	})

	plugin := &AegisPlugin{
		config: cfg,
		cache:  cache,
	}

	// Test
	score1, status := plugin.Score(context.Background(), nil, &v1.Pod{}, "node1")
	if !status.IsSuccess() {
		t.Errorf("Score failed for node1: %v", status)
	}

	score2, status := plugin.Score(context.Background(), nil, &v1.Pod{}, "node2")
	if !status.IsSuccess() {
		t.Errorf("Score failed for node2: %v", status)
	}

	if score1 <= score2 {
		t.Errorf("Expected node1 (low util) to have a higher score than node2 (high util). Got node1: %d, node2: %d", score1, score2)
	}
}

func TestFilterWithCapacity(t *testing.T) {
	cfg := DefaultConfig()
	cfg.MaxUtilThreshold = 0.8
	cache := NewPredictionCache(cfg.PredictionTTL)
	
	cache.UpdatePredictions(map[string]*NodePrediction{
		"node-good": {
			NodeName:     "node-good",
			PredictedCPU: 0.5,
			Timestamp:    time.Now(),
		},
		"node-bad": {
			NodeName:     "node-bad",
			PredictedCPU: 0.9,
			Timestamp:    time.Now(),
		},
	})

	plugin := &AegisPlugin{
		config: cfg,
		cache:  cache,
	}

	pod := &v1.Pod{}
	
	nodeGood := &v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-good"}}
	status := plugin.Filter(context.Background(), nil, pod, framework.NewNodeInfo(nodeGood))
	if !status.IsSuccess() {
		t.Errorf("Expected success for node-good, got %v", status)
	}

	nodeBad := &v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-bad"}}
	status = plugin.Filter(context.Background(), nil, pod, framework.NewNodeInfo(nodeBad))
	if status.Code() != framework.Unschedulable {
		t.Errorf("Expected Unschedulable for node-bad, got %v", status.Code())
	}
}

func TestFallbackOnMissingPrediction(t *testing.T) {
	cfg := DefaultConfig()
	cfg.FallbackScore = 75
	cache := NewPredictionCache(cfg.PredictionTTL)
	// Empty cache

	plugin := &AegisPlugin{
		config: cfg,
		cache:  cache,
	}

	// Filter should pass
	node := &v1.Node{ObjectMeta: metav1.ObjectMeta{Name: "node-unknown"}}
	status := plugin.Filter(context.Background(), nil, &v1.Pod{}, framework.NewNodeInfo(node))
	if !status.IsSuccess() {
		t.Errorf("Expected success (fallback) for filter, got %v", status)
	}

	// Score should be fallback
	score, status := plugin.Score(context.Background(), nil, &v1.Pod{}, "node-unknown")
	if !status.IsSuccess() || score != cfg.FallbackScore {
		t.Errorf("Expected fallback score %d, got %d (status %v)", cfg.FallbackScore, score, status)
	}
}

func TestCacheTTL(t *testing.T) {
	cache := NewPredictionCache(10 * time.Millisecond)
	cache.UpdatePredictions(map[string]*NodePrediction{
		"node1": {
			NodeName:     "node1",
			PredictedCPU: 0.5,
			Timestamp:    time.Now(),
		},
	})

	_, exists := cache.GetPrediction("node1")
	if !exists {
		t.Errorf("Expected prediction to exist")
	}

	time.Sleep(20 * time.Millisecond)

	_, exists = cache.GetPrediction("node1")
	if exists {
		t.Errorf("Expected prediction to be expired")
	}
}

func TestEnergyComputation(t *testing.T) {
	profile := &NodePowerProfile{
		PIdle: 100.0,
		PMax:  200.0,
		Alpha: 2.0,
	}

	// u=0 -> P=100
	p0 := ComputePower(0.0, profile)
	if p0 != 100.0 {
		t.Errorf("Expected 100.0, got %f", p0)
	}

	// u=0.5 -> P = 100 + 100*(0.25) = 125
	p5 := ComputePower(0.5, profile)
	if p5 != 125.0 {
		t.Errorf("Expected 125.0, got %f", p5)
	}

	// u=1.0 -> P=200
	p1 := ComputePower(1.0, profile)
	if p1 != 200.0 {
		t.Errorf("Expected 200.0, got %f", p1)
	}
}

func TestNormalizeScore(t *testing.T) {
	plugin := &AegisPlugin{}
	scores := framework.NodeScoreList{
		{Name: "n1", Score: 10},
		{Name: "n2", Score: 50},
		{Name: "n3", Score: 90},
	}

	status := plugin.NormalizeScore(context.Background(), nil, nil, scores)
	if !status.IsSuccess() {
		t.Errorf("NormalizeScore failed: %v", status)
	}

	if scores[0].Score != 0 {
		t.Errorf("Expected min score to be 0, got %d", scores[0].Score)
	}
	if scores[2].Score != 100 {
		t.Errorf("Expected max score to be 100, got %d", scores[2].Score)
	}
	if scores[1].Score != 50 {
		t.Errorf("Expected mid score to be 50, got %d", scores[1].Score)
	}
}
