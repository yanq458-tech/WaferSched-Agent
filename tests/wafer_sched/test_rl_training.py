"""Actual gradient updates, saved-model identity and original Policy integration."""

from dataclasses import asdict
import json

import numpy as np
import pytest
from sb3_contrib import MaskablePPO
import torch

from wafer_sched import Simulator, load_config
from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.policy_runner import run_policy
from wafer_sched.rl import WaferSchedulingEnv
from wafer_sched.rl.policy import TrainedPolicyAdapter
from wafer_sched.rl.training import load_training_config, masked_episode


def test_real_short_training_save_load_masked_prediction_and_policy_runner(tmp_path):
    torch.set_num_threads(1)
    config = load_config(PROJECT_ROOT / "configs/wafer_sched/S_small.json")
    env = WaferSchedulingEnv(config)
    model = MaskablePPO("MlpPolicy", env, seed=0, device="cpu", n_steps=32, batch_size=16,
                        n_epochs=2, gamma=1, policy_kwargs={"net_arch": [32, 32]})
    before = {key: value.clone() for key, value in model.policy.state_dict().items()}
    model.learn(total_timesteps=64)
    assert model.num_timesteps == 64
    assert any(not torch.equal(value, model.policy.state_dict()[key]) for key, value in before.items())
    path = tmp_path / "policy.zip"
    model.save(path)
    (tmp_path / "metadata.json").write_text(json.dumps({"schema": asdict(env.schema)}), encoding="utf-8")
    loaded = TrainedPolicyAdapter.load(path)
    for key, value in model.policy.state_dict().items():
        assert torch.equal(value, loaded.model.policy.state_dict()[key])
    vector, _ = env.reset(seed=7)
    a, _ = model.predict(vector, action_masks=env.action_masks(), deterministic=True)
    b, _ = loaded.model.predict(vector, action_masks=env.action_masks(), deterministic=True)
    np.testing.assert_array_equal(a, b)
    original = Simulator(config)
    result = run_policy(original, loaded)
    assert result.outcome["status"] == "completed"
    assert result.outcome["constraint_violations"] == 0
    summary = masked_episode(loaded.model, env, seed=0)
    assert summary["completion_rate"] == 1
    assert summary["mask_mismatches"] == 0
    assert env.simulator.trace == original.trace
    assert all(d["explanation"]["mask_valid"] for d in result.decisions)


@pytest.mark.parametrize("filename", ["smoke_training.json", "small_training.json", "medium_training.json"])
def test_declared_train_and_validation_configuration_valid_and_disjoint(filename):
    config = load_training_config(PROJECT_ROOT / "configs/wafer_sched/rl" / filename)
    assert config["gamma"] == 1.0
    assert config["total_timesteps"] % config["n_steps"] == 0
    assert config["max_training_seconds"] <= 600


def test_validation_overlap_cannot_be_hidden_by_renaming(tmp_path):
    original = PROJECT_ROOT / "configs/wafer_sched/rl/small_training.json"
    specification = json.loads(original.read_text(encoding="utf-8"))
    specification["validation_scenarios"] = [dict(specification["train_scenarios"][0], name="fake_holdout")]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(specification), encoding="utf-8")
    with pytest.raises(ValueError, match="overlaps"):
        load_training_config(path)
