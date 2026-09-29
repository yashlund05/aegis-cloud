package aegis

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"k8s.io/klog/v2"
)

// PredictionCache manages thread-safe node predictions with TTL eviction.
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
	klog.V(4).Info("Updated prediction cache successfully")
}

// FetchPredictions queries the predictor service and populates the cache.
func (c *PredictionCache) FetchPredictions(predictorURL string) error {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(predictorURL)
	if err != nil {
		return fmt.Errorf("failed to fetch predictions: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("predictor returned status %d", resp.StatusCode)
	}

	var preds []NodePrediction
	if err := json.NewDecoder(resp.Body).Decode(&preds); err != nil {
		return fmt.Errorf("failed to decode predictions: %w", err)
	}

	predMap := make(map[string]*NodePrediction)
	for i := range preds {
		predMap[preds[i].NodeName] = &preds[i]
	}
	c.UpdatePredictions(predMap)
	return nil
}

// StartBackgroundUpdater runs periodic non-blocking background synchronization with predictor.
func (c *PredictionCache) StartBackgroundUpdater(predictorURL string, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for range ticker.C {
			if err := c.FetchPredictions(predictorURL); err != nil {
				klog.V(4).Infof("Background prediction fetch warning: %v", err)
			}
		}
	}()
}
