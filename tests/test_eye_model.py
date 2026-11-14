"""Anatomical model eye of the 3D view: geometry and procedural textures (no OpenGL)."""
import math

import numpy as np
import pytest

from fundusview.ui import eye_model as em


def test_wall_profile_is_continuous_and_inside_the_globe():
    z = np.linspace(-em.R_RET + 0.05, em.IRIS_BACK_Z, 2000)
    r = em.wall_base_radius(z)
    assert np.all(np.abs(np.diff(r)) < 0.003)                             # no steps (ora included)
    assert em.wall_base_radius(em.Z_ORA - 1e-6) == pytest.approx(em.wall_base_radius(em.Z_ORA + 1e-6), abs=1e-4)
    outer = np.sqrt(1.0 - z ** 2)
    assert np.all(outer - r > 0.05)                                       # the wall has its thickness
    assert em.wall_base_radius(em.IRIS_BACK_Z) == pytest.approx(em.IRIS_ROOT_R)


def test_ciliary_processes_ring_the_lens_without_touching_it():
    phi = np.linspace(0, 2 * math.pi, 721)
    gaps = [em.wall_radius(z, phi).min() - em.lens_radius(z)
            for z in np.linspace(em.LENS_EQ_Z - 0.05, em.LENS_EQ_Z + 0.08, 14)]
    assert min(gaps) > 0.04                                               # room for the zonules …
    assert min(gaps) < 0.15                                               # … about 1 mm at the crests
    crests = em.ciliary_relief(0.705, phi[:-1])
    assert crests.max() == pytest.approx(em.PROCESS_HEIGHT, rel=0.05)
    peaks = np.sum((crests > np.roll(crests, 1)) & (crests >= np.roll(crests, -1)))   # around the ring
    assert peaks == em.CILIARY_PROCESSES
    assert em.ciliary_relief(em.Z_ORA, 0.0) == 0.0                         # pars plana is smooth


def test_inner_wall_mesh_faces_the_inside():
    m = em.inner_wall_mesh(n_post=40, n_ant=20, n_seg=144)
    p, n = m.pos.astype(np.float64), m.nrm.astype(np.float64)
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-4)
    away = np.linalg.norm(p, axis=1) > 1e-3
    assert np.mean(np.sum(n[away] * -p[away], axis=1) > 0) > 0.98
    assert np.linalg.norm(p, axis=1).max() < 0.96                        # inside the outer coat
    assert m.idx.max() < len(p) and m.idx.size % 3 == 0


@pytest.mark.parametrize("cut", [-0.2, 0.25, 0.5, 0.7, 0.81, 0.85, 0.95])
def test_section_faces_close_the_cut(cut):
    rim = em.rim_meshes(cut)
    zc = em.cut_plane_z(cut)
    wall = rim["wall"]
    assert np.allclose(wall.pos[:, 2], zc)
    r = np.hypot(wall.pos[:, 0], wall.pos[:, 1])
    inner, outer = r[: len(r) // 2], r[len(r) // 2:]
    assert np.allclose(outer, math.sqrt(1 - zc * zc) + 0.003)
    if zc <= em.IRIS_BACK_Z:
        phi = np.arctan2(wall.pos[: len(r) // 2, 1], wall.pos[: len(r) // 2, 0])
        assert np.allclose(inner, em.wall_radius(zc, phi) - 0.003, atol=1e-5)
    assert np.all(inner < outer)
    assert ("iris" in rim) == (em.IRIS_BACK_Z < zc <= em.IRIS_Z)
    assert ("lens" in rim) == (em.LENS_BACK_Z < zc < em.LENS_FRONT_Z)
    assert set(wall.uv[:, 0]) == {0.0, 1.0}                                 # 0 inner edge … 1 outer


def test_cut_never_reaches_past_the_limbus():
    assert em.cut_plane_z(0.99) == em.LIMBUS_Z
    assert em.cut_plane_z(0.3) == 0.3


def test_nerve_leaves_the_globe_behind_the_disc():
    p = np.array([math.sin(math.radians(21.5)), 0.02, -math.cos(math.radians(21.5))])
    m = em.nerve_mesh(p, "OD")
    tube = m.uv[:, 0] <= 1.0
    radius = np.linalg.norm(m.pos[tube], axis=1)
    assert radius.min() > em.R_RET + 0.05                    # never pokes into the eye
    assert radius.max() > 1.6                                # an ≈ 11 mm stump
    cap = m.uv[:, 0] > 2.5
    assert cap.any() and np.all(np.abs(m.uv[cap, 0] - 4.0) <= 1.0 + 1e-6)
    tip = m.pos[cap].mean(axis=0)
    assert np.dot(tip / np.linalg.norm(tip), p) > 0.9        # heads back toward the orbit apex


def test_muscles_sit_on_the_sclera_and_mirror_for_the_left_eye():
    od, os_ = em.muscle_mesh("OD"), em.muscle_mesh("OS")
    assert np.linalg.norm(od.pos, axis=1).min() > 0.995
    assert np.allclose(os_.pos[:, 0], -od.pos[:, 0]) and np.allclose(os_.pos[:, 1:], od.pos[:, 1:])
    assert np.isfinite(od.nrm).all()
    assert np.allclose(np.linalg.norm(od.nrm, axis=1), 1.0, atol=1e-3)
    # the medial rectus inserts closest to the limbus (spiral of Tillaux), on the nasal side (+x, OD)
    ins = {name: em.LIMBUS_ALPHA + mm * em.MM for name, _, mm, *_ in em.RECTI}
    assert min(ins, key=ins.get) == "MR"


def test_zonules_span_processes_to_lens_equator():
    z = em.zonule_lines()
    assert z.lines and len(z.pos) % 2 == 0
    a, b = z.pos[0::2], z.pos[1::2]
    ra, rb = np.hypot(a[:, 0], a[:, 1]), np.hypot(b[:, 0], b[:, 1])
    assert np.all(ra > rb) and np.all(rb > em.LENS_R * 0.75)


def test_iris_texture_is_a_brown_iris_around_a_black_pupil():
    t = em.iris_texture.__wrapped__(n=256)
    assert t.shape == (256, 256, 4) and t.dtype == np.uint8
    c = t.shape[0] // 2
    assert t[c, c, :3].max() < 20                                         # pupil
    ring = t[c, int(c * (1 + 0.6)), :3].astype(int)                       # ciliary zone, nasal
    assert ring[0] > ring[1] > ring[2]                                    # brown
    np.testing.assert_array_equal(t, em.iris_texture.__wrapped__(n=256))   # deterministic


def test_sclera_maps_are_white_with_red_vessels():
    a = em.sclera_anterior_texture.__wrapped__(n=512)
    p = em.sclera_posterior_texture.__wrapped__(n=256)
    assert a.shape == (512, 512, 3) and p.shape == (256, 256, 3)
    assert a.mean() > 170 and p.mean() > 170
    red = (a[..., 0].astype(int) - a[..., 1]) > 40
    assert 0.002 < red.mean() < 0.15                                      # vessels, but mostly white sclera
    c = a[256, 256].astype(int)
    assert c[2] >= c[0]                                                   # translucent bluish limbus


def test_periphery_texture_is_fundus_coloured():
    t = em.retina_periphery_texture.__wrapped__(n=256)
    mid = t[96:160, 96:160].reshape(-1, 3).mean(axis=0)
    assert mid[0] > mid[1] > mid[2]


def test_textures_are_cached_on_disk(tmp_path, monkeypatch):
    small = {"iris_texture": lambda: np.zeros((8, 8, 4), np.uint8),
             "sclera_anterior_texture": lambda: np.full((8, 8, 3), 200, np.uint8),
             "sclera_posterior_texture": lambda: np.full((8, 8, 3), 190, np.uint8),
             "retina_periphery_texture": lambda: np.full((8, 8, 3), 90, np.uint8)}
    for name, fn in small.items():
        monkeypatch.setattr(em, name, fn)
    first = em.load_textures(tmp_path)
    assert len(list((tmp_path / f"eye-textures-v{em.TEXTURE_VERSION}").glob("*.png"))) == 4

    def fail():
        raise AssertionError("should come from the cache")

    for name in small:
        monkeypatch.setattr(em, name, fail)
    again = em.load_textures(tmp_path)
    for k in first:
        np.testing.assert_array_equal(first[k], again[k])
