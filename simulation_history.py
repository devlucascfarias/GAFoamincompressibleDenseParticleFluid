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

    def add_entry(self, solver, case_path, start_time, end_time, status, notes=""):
        entry = {
            "solver": solver,
            "case_path": case_path,
            "start_time": start_time,
            "end_time": end_time,
            "status": status,
            "notes": notes
        }
        self.history.append(entry)
        self.save_history()

    def save_history(self):
        with open(self.history_file, "w") as file:
            json.dump(self.history, file, indent=4)

    def get_history(self):
        return self.history
