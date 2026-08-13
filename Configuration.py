import json
from datetime import datetime
from pydantic import BaseModel


class Config(BaseModel):
    gtfs_path: str = ""
    depot_path: str = ""
    routeTypes: list[str] = []
    date: datetime = datetime.today()

    generateDeadheadMat: bool = True
    api_key: str = ""
    deadheadFile: str = "config.json"

    minimumTerminal: int = 5
    maximumTerminal: int = 40

    @classmethod
    def generate_config(cls, filepath: str = 'config.json'):
        default_config = cls()
        with open(filepath, "w") as json_file:
            json.dump(default_config.model_dump(), json_file, indent=4)

def load_config(filepath: str = 'config.json') -> Config:
    with open(filepath) as json_file:
        config = json.load(json_file)
        return Config(**config)
