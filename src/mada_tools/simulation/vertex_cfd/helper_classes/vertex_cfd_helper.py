# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import glob
import json
import logging
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv

from mada_tools.simulation.simutils.samples.generation.lhs_sample_generator import (
    LHSampleGenerator,
)
from mada_tools.simulation.simutils.samples.output.folder_output_handler import (
    FolderOutputHandler,
)

LOG = logging.getLogger(__name__)


class VertexCFDHelper:
    """Stand alone Vertex-CFD Helper Class."""

    def __init__(self):
        LOG.info("Initialize Stand alone Vertex-CFD Helper Class.")
        self.output_dir = None
        self.step = None

    def generate_parameter_runs(
        self,
        num_samples: int,
        parameter_names: List[str],
        lower_bounds: List[float],
        upper_bounds: List[float],
        output_dir: str,
        input_deck_location: str | None = None,
        mesh_file_location: str | None = None,
    ) -> str:
        """
        Generate parameter runs for a Vertex-CFD parameter sweep study.

        Creates a structured directory with parameter files for each run,
        ready for job submission to a scheduler like Flux.

        Args:
            num_samples: Number of parameter sets to generate
            parameter_names: List of parameter names (e.g. ["vinit", "porosity"])
            lower_bounds: Lower bounds for each parameter dimension
            upper_bounds: Upper bounds for each parameter dimension
            output_dir: Directory where run folders will be created
            input_deck_location: Location of input deck; defaults to None
            mesh_file_location: Location of mesh file; defaults to None

        Returns:
            str: JSON string with run information for job submission
        """
        # Create output directory structure
        output_dir = os.path.abspath(output_dir)
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Create sample settings
        sample_settings = {
            "dims": len(parameter_names),
            "n_samples": num_samples,
            "lower_bounds": lower_bounds,
            "upper_bounds": upper_bounds,
        }

        # Create output settings
        output_settings = {
            "output_dir": output_dir,
            "param_file": "parameter_samples.txt",
        }

        # Generate the samples
        sample_generator = LHSampleGenerator()
        samples = sample_generator.generate(**sample_settings)

        # Store the generated samples
        output_handler = FolderOutputHandler()
        output_result = output_handler.write(samples, parameter_names, **output_settings)

        if input_deck_location is None:
            input_deck_location = os.path.join(
                os.environ["VERTEX_CFD_PATH"],
                "src/VERTEX-CFD/examples/inputs/incompressible/incompressible_2d_lid_driven_cavity.xml",
            )

        # Update run instances with command and args
        for run_instance in output_result.run_instances:
            # export LD_LIBRARY_PATH=/opt/cray/pe/cce/20.0.0/cce/x86_64/lib:$LD_LIBRARY_PATH must be in environment
            run_instance.command = os.path.join(os.environ["VERTEX_CFD_PATH"], "install/VERTEX-CFD/bin/vertexcfd")
            run_instance.args = [
                f"--i={os.path.join(run_instance.run_location, os.path.basename(input_deck_location))}",
            ]

            # Update input deck with parameters
            self._update_input_deck(run_instance.run_location, input_deck_location, mesh_file_location)

        # Convert run instances to the format expected by Flux using to_dict()
        run_info = {"runs": [run_instance.to_dict() for run_instance in output_result.run_instances]}

        # Update the run_instances.json file with command and args
        run_instances_json_path = os.path.join(output_dir, "run_instances.json")
        with open(run_instances_json_path, "w") as json_file:
            json.dump(run_info, json_file, indent=4)

        # Return run information as JSON for Flux to consume
        return True, json.dumps(run_info, indent=2)

    def _update_input_deck(self, run_location: str, input_deck_location: str, mesh_file_location: str):
        """
        Update input deck and its parameters.

        Args:
            run_location: Location of parameter run.
            input_deck_location: Location of input deck.
            mesh_file_location: Location of mesh file.

        """

        shutil.copy(input_deck_location, run_location)
        param_pairs = []
        with open(os.path.join(run_location, "parameter_samples.txt"), "r") as file:
            for line in file:
                param_pairs.append(line.strip().split(":"))

        new_input_deck_location = os.path.join(run_location, os.path.basename(input_deck_location))
        tree = ET.parse(new_input_deck_location)
        root = tree.getroot()

        # This updates the Boundary Conditions not the Initial Conditions which is what we want
        for param_pair in param_pairs:
            matches = root.findall(f".//Parameter[@name='{param_pair[0]}']")
            if not matches:
                raise ValueError(f"Parameter '{param_pair[0]}' not found in input deck.")

            for param in matches:
                param.set("value", param_pair[1].strip())

        if mesh_file_location is not None:
            matches = root.findall(".//Parameter[@name='File Name']")
            if not matches:
                raise ValueError("No mesh file found for this input deck.")

            for param in matches:
                param.set("value", mesh_file_location.strip())

        tree.write(new_input_deck_location, encoding="utf-8", xml_declaration=True)

    def post_process_runs(
        self,
        output_dir: str,
    ) -> str:
        """
        Post process parameter runs for a Vertex-CFD parameter sweep study.

        Looks through structured directory with parameter files for each run
        and post processes them.

        Args:
            output_dir: Directory where run folders were created

        Returns:
            tuple[bool, str]: Success flag and message
        """
        output_dir = os.path.abspath(output_dir)
        run_dirs = sorted(glob.glob(os.path.join(output_dir, "run*/")))

        png_all = os.path.join(output_dir, "probe_values_ALL.png")
        fig_all, axes_all = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

        # Probe for data extraction
        probe_xy = np.array([0.0, 0.0])
        probe_title = f"(x={probe_xy[0]}, y={probe_xy[1]})"

        # Cycle through the run directories
        for run_dir in run_dirs:
            LOG.info(f"Post processing {run_dir}")

            # Collect data from mesh
            run_data = self._collect_run_data(run_dir, probe_xy)
            if run_data is None:
                continue

            times = run_data["times"]
            merged_meshes = run_data["merged_meshes"]
            times, full_meshes = zip(*merged_meshes)
            probe_vel0 = run_data["probe_vel0"]
            probe_vel1 = run_data["probe_vel1"]
            probe_pres = run_data["probe_pres"]

            v0_min = run_data["v0_min"]
            v0_max = run_data["v0_max"]
            v1_min = run_data["v1_min"]
            v1_max = run_data["v1_max"]
            p_min = run_data["p_min"]
            p_max = run_data["p_max"]

            LOG.info(f"\ttime values: {times}")
            LOG.info(f"\tvelocity_0 clim = [{v0_min}, {v0_max}]")
            LOG.info(f"\tvelocity_1 clim = [{v1_min}, {v1_max}]")
            LOG.info(f"\tlagrange_pressure clim = [{p_min}, {p_max}]")

            if merged_meshes:
                _, full = merged_meshes[-1]
                LOG.info(f"\tpoint data: {list(full.point_data.keys())}")
                LOG.info(f"\tcell data: {list(full.cell_data.keys())}")
                LOG.info(f"\tfield data: {list(full.field_data.keys())}")
                LOG.info(f"\tarray names: {full.array_names}")

            # Mesh gif for individual run
            gif_name = "fields.gif"
            self._create_gif(
                run_dir,
                gif_name,
                times,
                full_meshes,
                v0_min,
                v0_max,
                v1_min,
                v1_max,
                p_min,
                p_max,
            )

            # Probe values for individual run
            png_out = os.path.join(run_dir, "probe_values.png")
            fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

            axes[0].plot(times, probe_vel0, marker="o")
            axes[0].set_ylabel("velocity_0")
            axes[0].set_title(f"Probe near {probe_title}")
            axes[0].grid(True)

            axes[1].plot(times, probe_vel1, marker="o")
            axes[1].set_ylabel("velocity_1")
            axes[1].grid(True)

            axes[2].plot(times, probe_pres, marker="o")
            axes[2].set_xlabel("time")
            axes[2].set_ylabel("lagrange_pressure")
            axes[2].grid(True)

            fig.tight_layout()
            fig.savefig(png_out, dpi=200)
            plt.close(fig)

            # Probe values for all runs
            run_label = os.path.basename(os.path.normpath(run_dir))

            axes_all[0].plot(times, probe_vel0, marker="o", label=run_label)
            axes_all[0].set_ylabel("velocity_0")
            axes_all[0].set_title(f"Probe near {probe_title} for all runs")
            axes_all[0].grid(True)

            axes_all[1].plot(times, probe_vel1, marker="o", label=run_label)
            axes_all[1].set_ylabel("velocity_1")
            axes_all[1].grid(True)

            axes_all[2].plot(times, probe_pres, marker="o", label=run_label)
            axes_all[2].set_xlabel("time")
            axes_all[2].set_ylabel("lagrange_pressure")
            axes_all[2].grid(True)

        axes_all[0].legend(fontsize="xx-small")
        fig_all.tight_layout()
        fig_all.savefig(png_all, dpi=200)
        plt.close(fig_all)

        return True, "Done post processing"

    def in_situ_viz(self) -> tuple[bool, dict]:
        """
        Create In Situ Visualization for GUI Chat Interface

        Returns:
            tuple[bool, dict]: Success flag and gif dict
        """

        # Only create gif for first run directory
        if self.output_dir is None:
            return True, {
                "gif_path": None,
                "status": "No run directory found",
                "step": None,
                "message": None,
                "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }

        matches = glob.glob(os.path.join(self.output_dir, "run0*"))
        run_dir = matches[0] if matches else None
        gif_name = "fields.gif"
        gif_out = os.path.join(run_dir, gif_name)

        probe_xy = np.array([0.0, 0.0])
        run_data = self._collect_run_data(run_dir, probe_xy)
        if run_data is None or not run_data["merged_meshes"]:
            return True, {
                "gif_path": None,
                "status": f"No visualization data found in {run_dir}",
                "step": None,
                "message": None,
                "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }

        merged_meshes = run_data["merged_meshes"]

        times, full_meshes = zip(*merged_meshes)
        if self.step is None:
            self.step = len(times)
        elif self.step == len(times):
            return True, {
                "gif_path": gif_out,
                "status": "No new simulation frame available.",
                "step": self.step,
                "message": f"Rendered t={times[-1]:.6f}",
                "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }
        else:
            self.step = len(times)

        v0_min = run_data["v0_min"]
        v0_max = run_data["v0_max"]
        v1_min = run_data["v1_min"]
        v1_max = run_data["v1_max"]
        p_min = run_data["p_min"]
        p_max = run_data["p_max"]

        self._create_gif(
            run_dir,
            gif_name,
            times,
            full_meshes,
            v0_min,
            v0_max,
            v1_min,
            v1_max,
            p_min,
            p_max,
        )

        return True, {
            "gif_path": gif_out,
            "status": "New simulation frame generated.",
            "step": self.step,
            "message": f"Rendered t={times[-1]:.6f}",
            "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        }

    def _collect_run_data(self, run_dir: str, probe_xy: np.ndarray) -> dict | None:
        """
        Load and aggregate time-dependent simulation data from an Exodus run directory.

        This method reads partitioned Exodus solution files from `run_dir`, merges
        mesh partitions for each available time step, extracts velocity and pressure
        fields, and samples those fields at the mesh point nearest to `probe_xy`.

        It also computes global minimum and maximum values across all time steps for
        `velocity_0`, `velocity_1`, and `lagrange_pressure`, which can be used for
        consistent plotting or color scaling.

        Args:
            run_dir: Path to the simulation run directory containing partitioned
                Exodus solution files matching `*_solution.exo*`.
            probe_xy: A 2D probe location as a NumPy array, used to sample the
                nearest mesh point at each time step.

        Returns:
            dict | None: A dictionary containing merged mesh data, probe values,
            time values, and field extrema, or `None` if no solution files or time
            values are found.

            Returned dictionary structure:

                {
                    "times": times,
                    "merged_meshes": [(time, merged_mesh), ...],
                    "probe_vel0": [...],
                    "probe_vel1": [...],
                    "probe_pres": [...],
                    "v0_min": float,
                    "v0_max": float,
                    "v1_min": float,
                    "v1_max": float,
                    "p_min": float,
                    "p_max": float,
                }

        Raises:
            KeyError: If any required field, `velocity_0`, `velocity_1`, or
                `lagrange_pressure`, is missing from a merged mesh's `point_data`.
        """
        # Parallelism splits the mesh up
        part_files = sorted(glob.glob(os.path.join(run_dir, "*_solution.exo*")))
        if not part_files:
            LOG.info("\tno solution files found, skipping")
            return None

        # Load mesh files up
        readers = [pv.get_reader(pf, force_ext=".exo") for pf in part_files]
        times = readers[0].time_values
        if len(times) == 0:
            LOG.info("\tno time values found, skipping")
            return None

        merged_meshes = []
        vel0_vals = []
        vel1_vals = []
        pres_vals = []
        probe_vel0 = []
        probe_vel1 = []
        probe_pres = []

        # Extract data for each time in the mesh
        for t in times:
            parts_t = []

            # Combine split meshes due to parallelism
            for reader in readers:
                reader.set_active_time_value(t)
                mesh = reader.read()

                # Assumes Exodus reader returns a nested multiblock structure where this is the main one
                main = mesh[0][0]
                parts_t.append(main)

            # Merge meshes for each timestep
            full = parts_t[0].merge(parts_t[1:])
            merged_meshes.append((t, full))

            if "velocity_0" not in full.point_data:
                raise KeyError(f"'velocity_0' not found in point_data for {run_dir}")
            if "velocity_1" not in full.point_data:
                raise KeyError(f"'velocity_1' not found in point_data for {run_dir}")
            if "lagrange_pressure" not in full.point_data:
                raise KeyError(f"'lagrange_pressure' not found in point_data for {run_dir}")

            v0 = full.point_data["velocity_0"]
            v1 = full.point_data["velocity_1"]
            p = full.point_data["lagrange_pressure"]

            vel0_vals.append(v0)
            vel1_vals.append(v1)
            pres_vals.append(p)

            # Closest physical location to probe_xy
            pts = full.points[:, :2]
            dist2 = np.sum((pts - probe_xy) ** 2, axis=1)
            idx = np.argmin(dist2)

            probe_vel0.append(v0[idx])
            probe_vel1.append(v1[idx])
            probe_pres.append(p[idx])

        return {
            "times": times,
            "merged_meshes": merged_meshes,
            "probe_vel0": probe_vel0,
            "probe_vel1": probe_vel1,
            "probe_pres": probe_pres,
            "v0_min": min(a.min() for a in vel0_vals),
            "v0_max": max(a.max() for a in vel0_vals),
            "v1_min": min(a.min() for a in vel1_vals),
            "v1_max": max(a.max() for a in vel1_vals),
            "p_min": min(a.min() for a in pres_vals),
            "p_max": max(a.max() for a in pres_vals),
        }

    def _create_gif(
        self,
        run_dir,
        gif_name,
        times,
        full_meshes,
        v0_min: float,
        v0_max: float,
        v1_min: float,
        v1_max: float,
        p_min: float,
        p_max: float,
    ) -> None:
        """
        Create an animated GIF of simulation fields over time.

        This method renders one frame per time step using a three-panel PyVista
        layout showing `velocity_0`, `velocity_1`, and `lagrange_pressure`. Each
        panel uses a fixed color scale across all frames so the animation remains
        visually consistent over time.

        Args:
            run_dir: Directory where the output GIF and per-frame PNG images are saved.
            gif_name: File name of the GIF to create.
            times: Sequence of simulation time values, one per frame.
            full_meshes: Sequence of merged meshes corresponding to `times`. Each
                mesh must contain the point-data fields `velocity_0`, `velocity_1`,
                and `lagrange_pressure`.
            v0_min: Global minimum value for `velocity_0` color scaling.
            v0_max: Global maximum value for `velocity_0` color scaling.
            v1_min: Global minimum value for `velocity_1` color scaling.
            v1_max: Global maximum value for `velocity_1` color scaling.
            p_min: Global minimum value for `lagrange_pressure` color scaling.
            p_max: Global maximum value for `lagrange_pressure` color scaling.

        Returns:
            None
        """
        plotter = pv.Plotter(shape=(1, 3), off_screen=True, window_size=(1800, 700))
        gif_out = os.path.join(run_dir, gif_name)
        plotter.open_gif(gif_out, fps=5)

        for i, (t, full) in enumerate(zip(times, full_meshes)):
            plotter.clear()

            plotter.subplot(0, 0)
            plotter.add_mesh(
                full,
                scalars="velocity_0",
                cmap="viridis",
                clim=[v0_min, v0_max],
                show_edges=False,
                scalar_bar_args={"title": "velocity_0"},
            )
            plotter.view_xy()
            plotter.show_bounds(xtitle=" ", ytitle=" ", grid=False, location="outer", all_edges=False)
            plotter.add_text(f"velocity_0, t = {t:.6f}", font_size=12)

            plotter.subplot(0, 1)
            plotter.add_mesh(
                full,
                scalars="velocity_1",
                cmap="viridis",
                clim=[v1_min, v1_max],
                show_edges=False,
                scalar_bar_args={"title": "velocity_1"},
            )
            plotter.view_xy()
            plotter.show_bounds(xtitle=" ", ytitle=" ", grid=False, location="outer", all_edges=False)
            plotter.add_text(f"velocity_1, t = {t:.6f}", font_size=12)

            plotter.subplot(0, 2)
            plotter.add_mesh(
                full,
                scalars="lagrange_pressure",
                cmap="viridis",
                clim=[p_min, p_max],
                show_edges=False,
                scalar_bar_args={"title": "lagrange_pressure"},
            )
            plotter.view_xy()
            plotter.show_bounds(xtitle=" ", ytitle=" ", grid=False, location="outer", all_edges=False)
            plotter.add_text(f"lagrange_pressure, t = {t:.6f}", font_size=12)

            plotter.write_frame()
            # Screenshots for progress
            plotter.screenshot(os.path.join(run_dir, f"frame_{i:04d}.png"))

        plotter.close()
