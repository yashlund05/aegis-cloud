package aegis

import (
	"sync"
	"time"

	"k8s.io/klog/v2"
)

// PredictionCache manages node predictions.
type PredictionCache struct {
	mu          sync.RWMutex
	predictions map[string]*NodePrediction
	ttl         time.Duration
}

// NewPredictionCache creates a new PredictionCache.
func NewPredictionCache(ttl time.Duration) *PredictionCache {
	return &PredictionCache{
		predictions: make(map[string]*NodePrediction),
		ttl:         ttl,
	}
}

// GetPrediction returns the cached prediction for a node if it is not expired.
func (c *PredictionCache) GetPrediction(nodeName string) (*NodePrediction, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	pred, exists := c.predictions[nodeName]
	if !exists {
		return nil, false
	}

	if time.Since(pred.Timestamp) > c.ttl {
		return nil, false // Expired
	}

	return pred, true
}

// UpdatePredictions updates the cache with new predictions.
func (c *PredictionCache) UpdatePredictions(predictions map[string]*NodePrediction) {
	c.mu.Lock()
	defer c.mu.Unlock()

	for k, v := range predictions {
		c.predictions[k] = v
	}
	klog.V(4).Info("Updated prediction cache")
}

// StartBackgroundUpdater stubs out a background fetcher for predictions.
func (c *PredictionCache) StartBackgroundUpdater(predictorURL string, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for range ticker.C {
			// TODO: Implement HTTP GET to predictorURL
			// klog.V(4).Info("Fetching predictions from ", predictorURL)
		}
	}()
}
