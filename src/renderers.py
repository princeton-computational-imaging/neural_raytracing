import torch
import torch.nn as nn
import torch.nn.functional as F
import random
import math

from .neural_blocks import ( SkipConnMLP, FourierEncoder )
from .utils import ( autograd, eikonal_loss, elev_azim_to_dir )
from .refl import ( LightAndRefl )

def load(args, shape, light_and_refl: LightAndRefl):
  assert(isinstance(light_and_refl, LightAndRefl)), "Need light and reflectance for integrator"

  if args.integrator_kind is None: return None
  elif args.integrator_kind == "direct": cons = Direct
  elif args.integrator_kind == "path": cons = Path
  else: raise NotImplementedError(f"load integrator: {args.integrator_kind}")

  if args.occ_kind is None: occ = lighting_wo_isect
  elif args.occ_kind is "hard": occ = lighting_w_isect
  else: raise NotImplementedError(f"load occlusion: {args.occ_kind}")

  integ = cons(shape, bsdf=light_and_refl.refl, light=light_and_refl.refl, occlusion=occ)

  return integ

# hard shadow lighting
def lighting_w_isect(pts, lights, isect_fn):
  dir, spectrum = lights(pts)
  rays = torch.cat([pts, dir], dim=-1)
  visible = isect_fn(rays)
  spectrum[~visible] = 0
  return dir, spectrum

# no shadow
def lighting_wo_isect(pts, lights, _isect_fn): return lights(pts)

class LearnedLighting(nn.Module):
  def __init__(self):
    self.attenuation = SkipConnMLP(
      in_size=5, out=1,
      xavier_init=True,
    )
  def forward(self, pts, lights, isect_fn):
    dir, spectrum = lights(pts)
    rays = torch.cat([pts, dir], dim=-1)
    visible = isect_fn(rays)
    att = self.attenuation(torch.cat([pts, elev_azim_to_dir(dir)], dim=-1))
    spectrum = torch.where(visible, spectrum, spectrum * att)
    return dir, spectrum

class Renderer(nn.Module):
  def __init__(
    self,
    shape,
    bsdf,
    light,

    occlusion=lighting_w_isect,
  ):
    super().__init__()
    self.shape = shape
    self.bsdf = bsdf
    self.light = light
    self.occ = occlusion
  def forward(self, _rays): raise NotImplementedError()

class Direct(Renderer):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
  def forward(self, rays):
    r_o, r_d = rays.split([3, 3], dim=-1)

    pts, hits, _t, n = self.shape.intersect_w_n(rays)
    # fast path no hits, a sync is painful but storing a bunch more memory for grads
    # for all 0s is worse.
    if not hits.any(): return torch.zeros_like(pts)

    light_dir, light_val = self.occ(pts, lights, self.shape.intersect_mask)
    bsdf_val = self.bsdf(x=pts, view=r_d, normal=n,light=light_dir)
    # TODO check this is valid
    print(hits.shape, bsdf_val.shape, light_val.shape)
    exit()
    return torch.where(
      hits,
      bsdf_val * light_val,
      torch.zeros_like(bsdf_val)
    )

class Path(Renderer):
  def __init__(
    self,
    bounces:int=1,
    **kwargs,
  ):
    super().__init__(**kwargs)
    self.bounces = bounces
  def forward(self, rays):
    raise NotImplementedError()
