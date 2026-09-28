package aegis

import (
	"time"
)

const (
	Name = "AegisScheduler"
)

// AegisPluginConfig holds the configuration for the Aegis scheduler plugin.
type AegisPluginConfig struct {
	WeightUtil       float64       `json:"weightUtil"`
	WeightEnergy     float64       `json:"weightEnergy"`
	WeightBalance    float64       `json:"weightBalance"`
	PredictionTTL    time.Duration `json:"predictionTTL"`
	FallbackScore    int64         `json:"fallbackScore"`
	MaxUtilThreshold float64       `json:"maxUtilThreshold"`
	PredictorURL     string        `json:"predictorURL"`
}

// NodePrediction holds the predicted utilization for a node.
type NodePrediction struct {
	NodeName     string        `json:"nodeName"`
	PredictedCPU float64       `json:"predictedCPU"` // 0.0 to 1.0
	PredictedMem float64       `json:"predictedMem"` // 0.0 to 1.0
	Timestamp    time.Time     `json:"timestamp"`
	Horizon      time.Duration `json:"horizon"`
}

// NodePowerProfile holds the power model parameters for a node.
type NodePowerProfile struct {
	PIdle float64 `json:"pIdle"`
	PMax  float64 `json:"pMax"`
	Alpha float64 `json:"alpha"`
}

// DefaultConfig provides default values for the plugin config.
func DefaultConfig() AegisPluginConfig {
	return AegisPluginConfig{
		WeightUtil:       1.0,
		WeightEnergy:     1.0,
		WeightBalance:    1.0,
		PredictionTTL:    30 * time.Second,
		FallbackScore:    50,
		MaxUtilThreshold: 0.9,
		PredictorURL:     "http://aegis-predictor:8080/predictions",
	}
}
