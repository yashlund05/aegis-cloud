package aegis

import (
	"math"
)

// ComputePower calculates the estimated power consumption based on CPU utilization and power profile.
func ComputePower(util float64, profile *NodePowerProfile) float64 {
	// Energy model: P_i(u_i) = P_idle + (P_max - P_idle) * u^alpha
	return profile.PIdle + (profile.PMax-profile.PIdle)*math.Pow(util, profile.Alpha)
}

// NormalizePowerCost normalizes power to a 0-1 range.
func NormalizePowerCost(power, minPower, maxPower float64) float64 {
	if maxPower == minPower {
		return 0.0
	}
	return (power - minPower) / (maxPower - minPower)
}

// GetNodePowerProfile retrieves the power profile for a node.
// For now, it returns a stubbed profile.
func GetNodePowerProfile(nodeName string) *NodePowerProfile {
	// TODO: Fetch from actual node labels or config.
	return &NodePowerProfile{
		PIdle: 50.0,
		PMax:  250.0,
		Alpha: 1.5,
	}
}
