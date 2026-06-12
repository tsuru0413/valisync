"""Generate a sample MF4 file for manual GUI testing."""

import numpy as np
from asammdf import MDF, Signal

mdf = MDF()
t = np.linspace(0, 10, 1000)

mdf.append([
    Signal(samples=np.sin(2 * np.pi * t), timestamps=t, name="SineWave"),
    Signal(samples=np.cos(2 * np.pi * t), timestamps=t, name="CosineWave"),
    Signal(samples=(t * 10).astype(np.int32), timestamps=t, name="Ramp"),
    Signal(samples=np.abs(np.sin(2 * np.pi * 0.5 * t)) * 100, timestamps=t, name="Speed_kph"),
])

import pathlib

output = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "sample.mf4"
output.parent.mkdir(parents=True, exist_ok=True)
mdf.save(str(output), overwrite=True)
print(f"Generated: {output}")
