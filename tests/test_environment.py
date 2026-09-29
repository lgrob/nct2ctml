"""
The statements of the environment agree: pyproject.toml (the Python
version and the dependency floors), requirements.txt (the same floors, for
pip), requirements.lock (the exact versions the suite was run with), and one
ruff version for CI, pre-commit and requirements-dev.txt.
"""

import os
import re
import sys
import tomllib
import unittest

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _version(text):
    return tuple(int(part) for part in re.findall(r"\d+", text))


def _requirements(path):
    """{name: floor} from lines like 'requests>=2.32.0'."""
    found = {}
    with open(os.path.join(ROOT, path)) as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                name, floor = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*>=\s*([0-9.]+)", line).groups()
                found[_normalise(name)] = floor
    return found


def _lock():
    pins = {}
    with open(os.path.join(ROOT, "requirements.lock")) as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                name, version = line.split("==")
                pins[_normalise(name)] = version
    return pins


with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
    PROJECT = tomllib.load(handle)["project"]


class TestEnvironment(unittest.TestCase):
    def test_pyproject_and_requirements_state_the_same_floors(self):
        declared = {}
        for spec in PROJECT["dependencies"]:
            name, floor = re.fullmatch(r"([A-Za-z0-9_.-]+)>=([0-9.]+)", spec).groups()
            declared[_normalise(name)] = floor
        self.assertEqual(declared, _requirements("requirements.txt"))

    def test_the_lock_pins_every_requirement_at_or_above_its_floor(self):
        pins = _lock()
        for name, floor in _requirements("requirements.txt").items():
            self.assertIn(name, pins, f"{name} is required but not locked")
            self.assertGreaterEqual(_version(pins[name]), _version(floor), name)

    def test_every_lock_line_is_an_exact_pin(self):
        with open(os.path.join(ROOT, "requirements.lock")) as handle:
            for line in handle:
                line = line.split("#", 1)[0].strip()
                if line:
                    self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*$")

    def test_this_interpreter_is_one_the_project_supports(self):
        floor = _version(re.fullmatch(r">=([0-9.]+)", PROJECT["requires-python"]).group(1))
        self.assertGreaterEqual(sys.version_info[: len(floor)], floor)

    def test_main_refuses_the_python_pyproject_excludes(self):
        with open(os.path.join(ROOT, "main.py")) as handle:
            guard = re.search(r"sys\.version_info < \((\d+), (\d+)\)", handle.read())
        floor = _version(PROJECT["requires-python"])
        self.assertIsNotNone(guard, "main.py has no Python version guard")
        self.assertEqual(tuple(int(g) for g in guard.groups()), floor[:2])

    def test_one_ruff_version_everywhere(self):
        with open(os.path.join(ROOT, "requirements-dev.txt")) as handle:
            pin = re.search(r"^ruff==([0-9.]+)$", handle.read(), re.M).group(1)
        with open(os.path.join(ROOT, ".pre-commit-config.yaml")) as handle:
            hooks = yaml.safe_load(handle)["repos"]
        revs = [r["rev"] for r in hooks if r["repo"].endswith("/ruff-pre-commit")]
        self.assertEqual(revs, [f"v{pin}"])
        with open(os.path.join(ROOT, ".github", "workflows", "lint.yml")) as handle:
            self.assertIn("pip install -r requirements-dev.txt", handle.read())

    def test_mypy_and_its_stubs_are_pinned(self):
        with open(os.path.join(ROOT, "requirements-dev.txt")) as handle:
            text = handle.read()
        for name in ("mypy", "types-PyYAML", "types-requests"):
            self.assertRegex(text, rf"(?m)^{name}==[0-9.]+$", name)


if __name__ == "__main__":
    unittest.main()
