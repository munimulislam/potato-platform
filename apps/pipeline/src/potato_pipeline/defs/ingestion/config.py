import dagster as dg


class TrialFileConfig(dg.Config):
    file_path: str
