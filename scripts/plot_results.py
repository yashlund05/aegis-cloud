import json
import os
import matplotlib.pyplot as plt
import numpy as np

def plot_pareto():
    with open('eval/real_pareto_results.json') as f:
        pareto = json.load(f)

    os.makedirs('docs/images', exist_ok=True)
    
    # Plot Pareto for a representative app (e.g., fadee4b59e71 which showed big differences)
    # or an average. Let's do an average across all apps.
    apps = pareto['apps']
    
    # We will average the energy and shortfall across apps for each CA util and Aegis tau
    aegis_taus = ['0.5', '0.7', '0.9', '0.99']
    ca_utils = ['0.5', '0.6', '0.7', '0.8', '0.9']
    
    avg_aegis = {t: {'energy': 0, 'shortfall': 0} for t in aegis_taus}
    avg_ca = {u: {'energy': 0, 'shortfall': 0} for u in ca_utils}
    
    n_apps = len(apps)
    
    for app_id, data in apps.items():
        for t in aegis_taus:
            avg_aegis[t]['energy'] += data['aegis_tau'][t]['energy_kwh'] / n_apps
            avg_aegis[t]['shortfall'] += data['aegis_tau'][t]['capacity_shortfall_minutes'] / n_apps
            
        for u in ca_utils:
            avg_ca[u]['energy'] += data['ca_util'][u]['energy_kwh'] / n_apps
            avg_ca[u]['shortfall'] += data['ca_util'][u]['capacity_shortfall_minutes'] / n_apps

    # Extract coordinates
    aegis_x = [avg_aegis[t]['shortfall'] for t in aegis_taus]
    aegis_y = [avg_aegis[t]['energy'] for t in aegis_taus]
    
    ca_x = [avg_ca[u]['shortfall'] for u in ca_utils]
    ca_y = [avg_ca[u]['energy'] for u in ca_utils]

    plt.figure(figsize=(8, 6))
    
    plt.plot(aegis_x, aegis_y, 'o-', label='Aegis (varying $\\tau$)', color='#2ca02c', markersize=8, linewidth=2)
    for i, t in enumerate(aegis_taus):
        plt.annotate(f'$\\tau$={t}', (aegis_x[i], aegis_y[i]), textcoords="offset points", xytext=(-10,-15), ha='center')

    plt.plot(ca_x, ca_y, 's--', label='Cluster Autoscaler (varying util %)', color='#1f77b4', markersize=8, linewidth=2)
    for i, u in enumerate(ca_utils):
        plt.annotate(f'{int(float(u)*100)}%', (ca_x[i], ca_y[i]), textcoords="offset points", xytext=(15,5), ha='left')

    plt.title('Energy vs Shortfall Pareto Frontier (Average across Real Traces)')
    plt.xlabel('Capacity Shortfall (minutes) -> Lower is better')
    plt.ylabel('Energy Consumption (kWh) -> Lower is better')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('docs/images/pareto_frontier.png', dpi=300)
    plt.close()


def plot_ablation():
    with open('eval/real_ablation_results.json') as f:
        abl = json.load(f)

    # Component costs (energy difference when component is removed)
    comp_costs = abl['component_cost_mean_over_apps']
    
    components = [
        'Minus Conformal',
        'Minus Proactive Forecast',
        'Minus Pod Placement',
        'Minus Node Power-Down'
    ]
    
    # Map the JSON keys to our labels
    energy_impact = [
        comp_costs['minus conformal']['d_energy_kwh'],
        comp_costs['minus forecast (reactive+consolidation)']['d_energy_kwh'],
        comp_costs['minus placement']['d_energy_kwh'],
        comp_costs['minus power-down']['d_energy_kwh']
    ]

    plt.figure(figsize=(10, 5))
    colors = ['#d62728' if v > 0 else '#2ca02c' for v in energy_impact]
    
    bars = plt.barh(components, energy_impact, color=colors, edgecolor='black')
    
    # Add vertical line at 0
    plt.axvline(0, color='black', linewidth=1)
    
    plt.title('Component Ablation: Energy Impact (Real Traces, SPECpower Calibrated)')
    plt.xlabel('Change in Energy vs Full Aegis (kWh)\nPositive means the component SAVES energy when present')
    
    # Add value labels
    for bar, val in zip(bars, energy_impact):
        if val >= 0:
            plt.text(val + 1, bar.get_y() + bar.get_height()/2, f'+{val:.1f}', va='center')
        else:
            plt.text(val - 1, bar.get_y() + bar.get_height()/2, f'{val:.1f}', va='center', ha='right')
            
    plt.tight_layout()
    plt.savefig('docs/images/component_ablation.png', dpi=300)
    plt.close()

if __name__ == '__main__':
    print("Generating Pareto Frontier...")
    plot_pareto()
    print("Generating Component Ablation...")
    plot_ablation()
    print("Graphs saved to docs/images/")
