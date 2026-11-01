"""Whole-frame observations collected before regional or numeric context."""
from copy import deepcopy
import json

AXES=("tone","color","brightness","lighting_naturalness","material_relationships","processing_appearance")
PROTECTIONS=("identity","layout","geometry","texture","ocr","naturalness","reference_content_leakage","unsupported_detail")
TEXT={"type":"string","minLength":1,"pattern":r"\S"}


def obj(properties):return dict(type="object",additionalProperties=False,required=list(properties),properties=properties)


OBSERVATION=obj(dict(reference_status={"enum":["achieved","partial","unmet","uncertain"]},
    relation={"enum":["closer","same","farther","uncertain"]},direction=TEXT,
    magnitude={"enum":["none","slight","moderate","large","unknown"]},confidence={"enum":["high","medium","low","unknown"]},evidence=TEXT))
STYLE_SCHEMA=obj({axis:deepcopy(OBSERVATION) for axis in AXES})
WHOLE_SCHEMA=obj(dict(image_sha256=obj({role:TEXT for role in ("source","appearance_reference","candidate","candidate_native")}),
    display=obj(dict(method={"enum":["side_by_side","toggle","sequential"]},scale=TEXT,color_basis=TEXT,note=TEXT)),
    reviewer=obj(dict(reviewer_id=TEXT,independence={"enum":["independent","same_model","unknown"]},prior_exposure=TEXT)),
    overall_style=STYLE_SCHEMA,preservation=obj({key:obj(dict(status={"enum":["pass","fail","uncertain"]},
        confidence={"enum":["high","medium","low","unknown"]},evidence=TEXT)) for key in PROTECTIONS}),
    conflicts={"type":"array","items":TEXT}))


def image_bindings(inputs):return {asset["role"]:asset["sha256"] for asset in inputs}


def validate_whole(value,bindings):
    from jsonschema import Draft202012Validator
    error=next(iter(Draft202012Validator(WHOLE_SCHEMA).iter_errors(value)),None)
    if error is not None:raise ValueError(error.message)
    json.dumps(value,allow_nan=False)
    if value["image_sha256"]!=bindings:raise ValueError("Whole-frame review belongs to different actual displayed files")
    for observation in value["overall_style"].values():
        if observation["relation"]=="uncertain" and observation["magnitude"]!="unknown":raise ValueError("Unknown relation requires unknown magnitude")
        if observation["reference_status"]=="achieved" and (observation["relation"]=="uncertain" or observation["confidence"]=="unknown"):
            raise ValueError("Uncertain whole-frame observation cannot certify achievement")
    return deepcopy(value)


def verdict_gate(whole):
    if any(row["status"]=="fail" for row in whole["preservation"].values()):return "reject"
    if whole["conflicts"] or any(row["status"]=="uncertain" or row["confidence"]=="unknown" for row in whole["preservation"].values()) or any(
        row["reference_status"]=="uncertain" or row["confidence"]=="unknown" for row in whole["overall_style"].values()):return "uncertain"
    if any(row["reference_status"]!="achieved" for row in whole["overall_style"].values()):return "revise"
    return "accept"
