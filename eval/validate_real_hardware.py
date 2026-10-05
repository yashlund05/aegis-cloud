import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
import services
from services.energy_module.kepler import KeplerClient
from services.energy_module.power_model import compute_power, compute_energy_kwh

async def main():
    print("=" * 80)
    print("  LIVE HARDWARE/KEPLER VALIDATION")
    print("=" * 80)
    url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    client = KeplerClient(url)
    
    print(f"[*] Querying physical pod energy from Kepler at {url}...")
    pod_energy = await client.get_pod_energy()
    
    if not pod_energy:
        print("[!] No Kepler data returned. Is Prometheus reachable and Kepler running?")
        print("[*] Note: The analytic simulator will be used instead of real physical validation.")
        return
        
    print(f"[*] Retrieved physical energy measurements for {len(pod_energy)} pods:")
    for pod, energy in pod_energy.items():
        print(f"    - {pod}: {energy:.2f} J")
        
    total_joules = sum(pod_energy.values())
    total_kwh = total_joules / (3600.0 * 1000.0)
    print(f"\n[*] Total Measured Physical Energy: {total_kwh:.6f} kWh")
    print("[*] Validation successful. These measurements can now be compared against the analytic model.")

if __name__ == "__main__":
    asyncio.run(main())
