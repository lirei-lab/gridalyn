import pandas as pd
import numpy as np

class GridLoadFacade:
    """
    Central API for generating stochastic grid load trajectories.
    Allows seamless toggling between purely mathematical ARX generators
    and explicit physical Thermodynamic models.
    """
    
    @classmethod
    def generate_loads(
        cls, 
        generator_type: str, 
        df_weather: pd.Series, 
        n_houses: int, 
        resolution_minutes: int, 
        seed: int
    ):
        """
        Natively routes the load generation to the requested simulation engine.
        
        Args:
            generator_type: "parametric" (ARX math) or "thermodynamic" (RC physics)
            df_weather: The target outdoor temperature trajectory.
            n_houses: Number of independent stochastic traces to generate.
            resolution_minutes: Step size for the returned matrix.
            seed: RNG seed for reproducible generation.
            
        Returns:
            A tuple (heat_kw_matrix, bg_kw_matrix) of shape (time_steps, n_houses).
        """
        target_freq = f"{resolution_minutes}min"
        native_res_temp = df_weather.resample(target_freq).mean().interpolate()
        
        if generator_type == "parametric":
            from gridalyn.simulation.simulators.agents.unmanaged_loads import ParametricArxGenerator
            gen = ParametricArxGenerator()
            gen.load()
            
            # Enforce native rng seed mapping to tie identical stochastic households 
            # consistently to the exact Monte Carlo spatial node instance!
            np.random.seed(seed)
            return gen.generate(native_res_temp, n_houses=n_houses)
            
        elif generator_type == "thermodynamic":
            from gridalyn.simulation.simulators.agents.fleet import make_buildings, simulate_buildings
            
            # Generate the strict array of explicitly tracked homes
            buildings = make_buildings(n_houses, seed=seed)
            
            # The simulator steps natively and returns a detailed physics state matrix
            bld_results = simulate_buildings(buildings, native_res_temp)
            
            time_steps = len(native_res_temp)
            heat_kw_matrix = np.zeros((time_steps, n_houses))
            bg_kw_matrix = np.zeros((time_steps, n_houses))
            
            for i in range(n_houses):
                heat_kw_matrix[:, i] = bld_results[i]["p_heat_kw"].values
                bg_kw_matrix[:, i] = bld_results[i]["p_bg_kw"].values
                
            return heat_kw_matrix, bg_kw_matrix
            
        else:
            raise ValueError(f"Unknown generator_type: {generator_type}. Must be 'parametric' or 'thermodynamic'.")
