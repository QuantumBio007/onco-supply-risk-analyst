import numpy as np
import matplotlib.pyplot as plt

def simulate_inventory(
    days=365,
    daily_mean_demand=8,
    lead_time=10,
    reorder_point=40,
    order_quantity=80,
    initial_inventory=60,
    seed=0,
    plot=True
):
    rng = np.random.default_rng(seed)

    inventory = initial_inventory
    pipeline_orders = []  # list of (quantity, arrival_day)
    inventory_history = []
    stockout_days = 0
    total_demand = 0
    total_fulfilled = 0

    for day in range(days):
        # 1) Demand
        demand = rng.poisson(daily_mean_demand)
        total_demand += demand

        # 2) Receive orders
        arrivals = [q for q, t in pipeline_orders if t == day]
        if arrivals:
            inventory += sum(arrivals)
        pipeline_orders = [(q, t) for q, t in pipeline_orders if t > day]

        # 3) Fulfill demand
        if demand > inventory:
            stockout_days += 1
            total_fulfilled += inventory
            inventory = 0
        else:
            inventory -= demand
            total_fulfilled += demand

        # 4) Reorder decision
        if inventory <= reorder_point:
            pipeline_orders.append((order_quantity, day + lead_time))

        # 5) Track
        inventory_history.append(inventory)

    avg_inventory = float(np.mean(inventory_history))
    service_level_days = 1 - stockout_days / days
    service_level_units = total_fulfilled / total_demand

    results = {
        "stockout_days": stockout_days,
        "avg_inventory": avg_inventory,
        "service_level_days": service_level_days,
        "service_level_units": service_level_units,
        "inventory_history": inventory_history,
    }

    if plot:
        plt.figure(figsize=(10, 4))
        plt.plot(inventory_history, label='Inventory level')
        plt.axhline(reorder_point, color='red', linestyle='--', label='Reorder point')
        plt.xlabel('Day')
        plt.ylabel('Units in stock')
        plt.title('Simple oncology drug inventory simulation')
        plt.legend()
        plt.tight_layout()
        plt.show()

    return results

if __name__ == "__main__":
    res = simulate_inventory()
    print(f"Stockout days: {res['stockout_days']}")
    print(f"Average inventory: {res['avg_inventory']:.1f}")
    print(f"Service level (days without stockout): {res['service_level_days']:.3f}")
    print(f"Service level (units fulfilled): {res['service_level_units']:.3f}")
