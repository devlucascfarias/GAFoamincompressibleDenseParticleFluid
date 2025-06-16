import json
import os

class SimulationHistory:
    def __init__(self, history_file="simulation_history.json"):
        self.history_file = history_file
        self.history = self.load_history()

    def load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as file:
                return json.load(file)
        return []

    def extract_relevant_log_data(self, log_path):
        """Extrai o último bloco 'Solving 2-D cloud cloud\nCloud: cloud' do log.foamRun."""
        if not os.path.exists(log_path):
            return []
        with open(log_path, "r") as f:
            lines = f.readlines()
        start_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("Solving 2-D cloud cloud"):
                if i + 1 < len(lines) and lines[i + 1].startswith("Cloud: cloud"):
                    start_idx = i
                    break
        if start_idx is not None:
            end_idx = start_idx + 1
            for j in range(start_idx + 2, len(lines)):
                if lines[j].startswith("Solving 2-D cloud cloud"):
                    break
                end_idx = j
            bloco = [line.rstrip() for line in lines[start_idx:end_idx + 1]]
            return bloco
        return []

    def add_entry(self, solver, case_path, start_time, end_time, status, notes=""):
        log_path = os.path.join(case_path, "log.foamRun")
        log_data = self.extract_relevant_log_data(log_path)
        entry = {
            "solver": solver,
            "case_path": case_path,
            "start_time": start_time,
            "end_time": end_time,
            "status": status,
            "notes": notes,
            "log_data": log_data
        }
        self.history.append(entry)
        self.save_history()

    def save_history(self):
        with open(self.history_file, "w") as file:
            json.dump(self.history, file, indent=4)

    def get_history(self):
        return self.history
    
    def get_cloud_properties_params(self, cloud_properties_path):
        """Extrai os principais parâmetros numéricos do cloudProperties."""
        if not os.path.exists(cloud_properties_path):
            return {}
        params = {}
        with open(cloud_properties_path, "r") as f:
            lines = f.readlines()
        for line in lines:
            if ';' in line and not line.strip().startswith('//'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        params[parts[0]] = float(parts[1].replace(';',''))
                    except Exception:
                        pass
        return params

    def get_ml_dataset(self):
        """Monta um dataset com parâmetros do cloudProperties e resultados do log para cada simulação."""
        import re
        dataset = []
        for entry in self.history:
            case_path = entry["case_path"]
            cloud_path = os.path.join(case_path, "constant", "cloudProperties")
            params = self.get_cloud_properties_params(cloud_path)
            log_data = entry.get("log_data", [])
            max_cell_vol = None
            kinetic_energy = None
            for line in log_data:
                m = re.search(r"Max cell volume fraction\s*=\s*([0-9.eE+-]+)", line)
                if m:
                    max_cell_vol = float(m.group(1))
                m2 = re.search(r"Linear kinetic energy\s*=\s*([0-9.eE+-]+)", line)
                if m2:
                    kinetic_energy = float(m2.group(1))
            row = {**params, "max_cell_volume_fraction": max_cell_vol, "kinetic_energy": kinetic_energy}
            dataset.append(row)
        return dataset
