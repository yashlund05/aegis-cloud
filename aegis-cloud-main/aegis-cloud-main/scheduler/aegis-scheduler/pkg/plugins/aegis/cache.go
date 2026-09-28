package aegis

import (
	"encoding/json"
	"net/http"
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

// StartBackgroundUpdater runs a background fetcher for predictions.
func (c *PredictionCache) StartBackgroundUpdater(predictorURL string, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		client := &http.Client{Timeout: 5 * time.Second}
		for range ticker.C {
			resp, err := client.Get(predictorURL)
			if err != nil {
				klog.Errorf("Failed to fetch predictions from %s: %v", predictorURL, err)
				continue
			}
			
			var predictionsList []NodePrediction
			if err := json.NewDecoder(resp.Body).Decode(&predictionsList); err != nil {
				klog.Errorf("Failed to decode predictions: %v", err)
				resp.Body.Close()
				continue
			}
			resp.Body.Close()
			
			newPreds := make(map[string]*NodePrediction)
			for i := range predictionsList {
				p := predictionsList[i]
				p.Timestamp = time.Now()
				newPreds[p.NodeName] = &p
			}
			
			c.UpdatePredictions(newPreds)
		}
	}()
}
