"""Builds config/color/sg_pipeline.ocio from OCIO's built-in ACES 1.3 studio config (OCIO 2.1 profile)."""
import sys
import PyOpenColorIO as ocio

out = sys.argv[1]
cfg = ocio.Config.CreateFromBuiltinConfig("studio-config-v1.0.0_aces-v1.3_ocio-v2.1")
cfg.setName("sg_pipeline")
cfg.setDescription(
    "sg_pipeline studio colour config: OCIO built-in studio-config-v1.0.0_aces-v1.3_ocio-v2.1 "
    "(ACES 1.3, OCIO 2.1 profile so Mari 7.1 reads it) with file rules for this pipeline: "
    "8-bit textures and plates (png, jpg, tif) are sRGB - Texture, renders and HDRIs (exr, hdr) "
    "are ACEScg, anything else falls back to ACES2065-1. Data maps (roughness, metallic, normal, "
    "height) are set to Raw by the loaders."
)
rules = cfg.getFileRules()
# inserted before the Default rule, in order of priority
for index, (name, space, ext) in enumerate([
    ("PNG textures and plates", "sRGB - Texture", "png"),
    ("JPEG textures and plates", "sRGB - Texture", "jpg"),
    ("JPEG (jpeg)", "sRGB - Texture", "jpeg"),
    ("TIFF textures", "sRGB - Texture", "tif"),
    ("TIFF (tiff)", "sRGB - Texture", "tiff"),
    ("EXR renders", "ACEScg", "exr"),
    ("HDR environment maps", "ACEScg", "hdr"),
]):
    rules.insertRule(index, name, space, "*", ext)
cfg.setFileRules(rules)
cfg.validate()
open(out, "w", encoding="utf-8", newline="\n").write(cfg.serialize())

check = ocio.Config.CreateFromFile(out)
for path in ("lantern_basecolor.1001.png", "beauty.0001.exr", "studio.hdr", "scan.abc"):
    print("RULE", path, "->", check.getColorSpaceFromFilepath(path))
print("PROFILE", check.getMajorVersion(), check.getMinorVersion(), "OCIO", ocio.GetVersion())
