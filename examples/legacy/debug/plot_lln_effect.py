import numpy as np
import matplotlib.pyplot as plt

def main():
    n_houses = 3000
    n_steps = 288
    
    # Simulate single house base load with large noise (std ~ 30% of mean)
    mean_profile = np.sin(np.linspace(0, np.pi, n_steps)) + 1.0 # arbitrary smooth curve

    # Generate 30 realizations of the ENTIRE 3000-house grid WITHOUT macro noise
    plt.figure(figsize=(12, 6))
    
    for i in range(10):
        # 3000 houses, uncorrelated random noise
        # This completely mimics the individual house stochastic AR(1) logic!
        noise = np.random.normal(0, 0.4, size=(n_steps, n_houses))
        # Add shape
        house_profiles = mean_profile[:, None] * np.exp(noise)
        
        # Aggregate the town
        town_aggregate = np.sum(house_profiles, axis=1) / n_houses
        
        plt.plot(town_aggregate, color='blue', alpha=0.3)
        
    plt.plot(mean_profile * np.exp(0.4**2 / 2), color='red', label='True Mathematical Expectation')
    plt.title("Law of Large Numbers (N=3000 Houses)")
    plt.xlabel("Timesteps")
    plt.ylabel("Avg load per house (kW)")
    plt.legend()
    plt.savefig("examples/generated/outputs/lln_effect.png")

if __name__ == "__main__":
    main()
