"""A loaded MaskablePPO consumes only the existing immutable Policy interface."""

from dataclasses import asdict
import json

import numpy as np
from sb3_contrib import MaskablePPO

from .encoding import ActionEncoder, EncodingSchema, ObservationEncoder
from ..infrastructure.paths import resolve_path


class TrainedPolicyAdapter:
    name = "maskable_ppo"

    def __init__(self, model, schema=EncodingSchema(), *, deterministic=True):
        self.model, self.schema, self.deterministic = model, schema, deterministic
        self.observation_encoder, self.action_encoder = ObservationEncoder(schema), ActionEncoder(schema)
        if model.action_space.n != schema.action_count or model.observation_space.shape != (schema.observation_size,):
            raise ValueError("Model spaces do not match the saved encoding schema")
        self.last_decision = {}

    @classmethod
    def load(cls, model_path, metadata_path=None):
        path = resolve_path(model_path)
        metadata_path = metadata_path or path.parent / "metadata.json"
        metadata = json.loads(resolve_path(metadata_path).read_text(encoding="utf-8"))
        return cls(MaskablePPO.load(path, device="cpu"), EncodingSchema(**metadata["schema"]))

    def select_action(self, observation, legal_actions):
        if not legal_actions:
            raise ValueError("Policy requires a nonempty original legal catalogue")
        vector = self.observation_encoder.encode(observation)
        mask = self.action_encoder.mask(observation, legal_actions)
        index, _ = self.model.predict(vector, deterministic=self.deterministic, action_masks=mask)
        index = int(index)
        operation = self.action_encoder.decode(index, observation, legal_actions)
        self.last_decision = {"rule": self.name, "action_index": index,
                              "legal_action_indices": np.flatnonzero(mask).tolist(),
                              "mask_valid": bool(mask[index]), "schema": asdict(self.schema)}
        return operation
