"""
Unit tests for the Vertex-CFD MCP server and each of its tools.
"""

import io
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import pandas as pd
import pytest
import pyvista as pv
from PIL import Image

from mada_tools.simulation.vertex_cfd.helper_classes.vertex_cfd_helper import VertexCFDHelper


@pytest.fixture
def vertex_cfd_generated_runs(simulation_testing_dir: Path, configure_env) -> tuple[Path, int, list[str]]:
    """Create Vertex CFD test input and generate parameter sweep runs.

    This fixture sets up a temporary Vertex CFD working directory, writes a
    minimal dummy XML input file, configures the Vertex CFD environment, and
    generates a set of parameter runs for testing.

    Returns:
        A tuple containing:
            - output directory path
            - number of runs generated
            - parameter names used for generation
    """
    output_dir = simulation_testing_dir / "vertex_cfd"
    output_dir.mkdir(parents=True, exist_ok=True)

    vertex_cfd_helper = VertexCFDHelper()

    runs = 10
    parameter_names = ["velocity_0", "velocity_1"]

    with configure_env("vertex_cfd"):
        vertex_cfd_helper.generate_parameter_runs(
            runs,
            parameter_names,
            [0, 10],
            [10, 20],
            str(output_dir),
        )

    return output_dir, runs, parameter_names


@pytest.mark.requires_env("MCP_SERVER:vertex_cfd")
@pytest.mark.requires_gitlab_runner
def test_generate_parameter_runs(vertex_cfd_generated_runs: Path):
    """Verify generated Vertex CFD parameter runs and output metadata.

    This test validates that the fixture-created run directories exist,
    the run_parameters.csv file is present with the expected columns and
    run IDs, and each run's parameter_samples.txt file contains the expected
    sampled parameter values.
    """
    output_dir, runs, parameter_names = vertex_cfd_generated_runs

    for i in range(runs):
        run_dir = output_dir / f"run{i:02d}"
        assert run_dir.exists(), f"Missing directory: {run_dir}"
        assert run_dir.is_dir(), f"Not a directory: {run_dir}"

    parameters_csv = output_dir / "run_parameters.csv"
    assert parameters_csv.exists(), f"Missing file: {parameters_csv}"
    assert parameters_csv.is_file(), f"Not a file: {parameters_csv}"

    df = pd.read_csv(parameters_csv, dtype={"run#": str})

    assert list(df.columns) == ["run#", *parameter_names]
    assert df["run#"].tolist() == [f"{i:02d}" for i in range(runs)]

    for _, row in df.iterrows():
        run_id = row["run#"]
        run_dir = output_dir / f"run{run_id}"
        samples_file = run_dir / "parameter_samples.txt"

        assert samples_file.exists(), f"Missing file: {samples_file}"
        assert samples_file.is_file(), f"Not a file: {samples_file}"

        sample_values = {}
        with samples_file.open() as f:
            for line in f:
                key, value = line.strip().split(": ", maxsplit=1)
                sample_values[key] = float(value)

        for param in parameter_names:
            assert param in sample_values, f"Missing parameter {param} in {samples_file}"
            assert sample_values[param] == pytest.approx(row[param]), (
                f"Mismatch for {param} in {samples_file}, expected {row[param]}, got {sample_values[param]}"
            )


@pytest.mark.requires_env("MCP_SERVER:vertex_cfd")
@pytest.mark.requires_gitlab_runner
def test_post_process_runs(vertex_cfd_generated_runs: Path, monkeypatch):
    """Verify post-processing of generated Vertex CFD runs.

    This test creates synthetic PyVista meshes and time series data to emulate
    simulation output, then exercises the post-processing workflow to confirm it
    can read the generated runs and process field data correctly without relying
    on a real Exodus file or interactive rendering.
    """
    output_dir, runs, parameter_names = vertex_cfd_generated_runs

    # Create fake mesh
    n_time = 5
    n_res = 2

    left_base = pv.Plane(
        center=(-0.5, 0.0, 0.0),
        i_size=1.0,
        j_size=1.0,
        i_resolution=n_res,
        j_resolution=n_res,
    ).triangulate()

    right_base = pv.Plane(
        center=(0.5, 0.0, 0.0),
        i_size=1.0,
        j_size=1.0,
        i_resolution=n_res,
        j_resolution=n_res,
    ).triangulate()

    left_seq = []
    right_seq = []
    times = np.arange(n_time, dtype=float)

    for t in times:
        left = left_base.copy()
        lx = left.points[:, 0]
        ly = left.points[:, 1]
        left.point_data["velocity_0"] = lx + t
        left.point_data["velocity_1"] = ly + 2.0 * t
        left.point_data["lagrange_pressure"] = lx * lx + ly * ly + 3.0 * t
        left_seq.append(left)

        right = right_base.copy()
        rx = right.points[:, 0]
        ry = right.points[:, 1]
        right.point_data["velocity_0"] = rx + t
        right.point_data["velocity_1"] = ry + 2.0 * t
        right.point_data["lagrange_pressure"] = rx * rx + ry * ry + 3.0 * t
        right_seq.append(right)

    # Need this because this isn't really an Exodus file
    class DummyReader:
        def __init__(self, seq):
            self._seq = seq
            self.time_values = times
            self._idx = 0

        def set_active_time_value(self, t):
            self._idx = int(np.where(np.isclose(self.time_values, t))[0][0])

        def read(self):
            return pv.MultiBlock([pv.MultiBlock([self._seq[self._idx]])])

    # Need this because VTK/PyVista rendering in headless CI
    class FakePlotter:
        def __init__(self, *args, **kwargs):
            self.gif_path = None
            self.frames = []
            self.col = 0
            self.panels = {}

        def open_gif(self, path, fps):
            self.gif_path = Path(path)
            self.fps = fps

        def clear(self):
            self.col = 0
            self.panels = {}

        def subplot(self, row, col):
            self.col = col

        def add_mesh(self, mesh, scalars=None, cmap="viridis", clim=None, scalar_bar_args=None, **kwargs):
            self.panels[self.col] = {
                "mesh": mesh.copy(),
                "scalars": scalars,
                "cmap": cmap,
                "clim": clim,
                "title": scalar_bar_args["title"] if scalar_bar_args and "title" in scalar_bar_args else scalars,
                "text": None,
            }

        def view_xy(self):
            pass

        def add_text(self, text, **kwargs):
            if self.col in self.panels:
                self.panels[self.col]["text"] = text

        def write_frame(self):
            fig, axes = plt.subplots(1, 3, figsize=(15, 4))

            for col in range(3):
                panel = self.panels[col]
                mesh = panel["mesh"]
                vals = mesh.point_data[panel["scalars"]]

                x = mesh.points[:, 0]
                y = mesh.points[:, 1]
                triangles = mesh.faces.reshape(-1, 4)[:, 1:4]
                tri = mtri.Triangulation(x, y, triangles)

                clim = panel["clim"] or [None, None]

                im = axes[col].tripcolor(
                    tri,
                    vals,
                    shading="gouraud",
                    cmap=panel["cmap"],
                    vmin=clim[0],
                    vmax=clim[1],
                )
                axes[col].set_aspect("equal")
                axes[col].set_title(panel["text"] or panel["title"])
                fig.colorbar(im, ax=axes[col])

            fig.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=120)
            plt.close(fig)
            buf.seek(0)
            self.frames.append(Image.open(buf).convert("P"))

        def close(self):
            if not self.frames:
                Image.new("P", (10, 10), 255).save(self.gif_path, format="GIF")
                return

            self.frames[0].save(
                self.gif_path,
                save_all=True,
                append_images=self.frames[1:],
                duration=200,
                loop=0,
                format="GIF",
            )

        def show_bounds(self, xtitle=" ", ytitle=" ", grid=False, location="outer", all_edges=False):
            self.xtitle = xtitle
            self.ytitle = ytitle
            self.grid = grid
            self.location = location
            self.all_edges = all_edges

        def screenshot(self, png_path):
            self.path = png_path

    reader_map = {}

    for i in range(runs):
        run_dir = output_dir / f"run{i:02d}"

        part0 = run_dir / "part0_solution.exo"
        part1 = run_dir / "part1_solution.exo"

        part0.write_text("", encoding="utf-8")
        part1.write_text("", encoding="utf-8")

        reader_map[str(part0)] = DummyReader(left_seq)
        reader_map[str(part1)] = DummyReader(right_seq)

    def fake_get_reader(path, force_ext=None):
        return reader_map[str(path)]

    monkeypatch.setattr(pv, "get_reader", fake_get_reader)
    monkeypatch.setattr(pv, "Plotter", FakePlotter)

    vertex_cfd_helper = VertexCFDHelper()

    ok, msg = vertex_cfd_helper.post_process_runs(str(output_dir))

    assert ok is True
    assert msg == "Done post processing"
    assert (output_dir / "probe_values_ALL.png").exists()

    for i in range(runs):
        print(output_dir)
        run_dir = output_dir / f"run{i:02d}"
        assert (run_dir / "probe_values.png").exists()
        assert (run_dir / "fields.gif").exists()
