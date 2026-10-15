"""Archive Work Diagnoser observations made after individually viewing 12 inputs.

This is a transcription of actual image inspection, not a metadata-based
diagnoser or an inference substitute. The other eight records are independent
Work-agent observations. No reference image, local-model output or restoration
was used to author these payloads.
"""
import argparse
from pathlib import Path

from hir_manual.protocol import validate_schema
from hir_manual.storage import now, read_json, sha256_file, write_json


def degradation(kind, severity, spatial, location, worst, mildest, evidence):
    return dict(type=kind, severity=severity, spatial=spatial, location=location,
                worst_at=worst, mildest_at=mildest, evidence=evidence)


def diagnosis(content, degradations, flags, notes, tools, difficulty, reason):
    return dict(content=content, degradations=degradations,
                sensitive=dict(zip(("has_text", "has_faces", "has_layered_depth",
                                    "has_complex_semantics"), flags), notes=notes),
                tool_plan=[dict(tool=tool, reason=why) for tool, why in tools],
                difficulty_hint=difficulty, difficulty_reason=reason)


# All descriptions below were authored after viewing the individual canonical
# images in the current Work conversation. They intentionally avoid guessing
# unreadable letters or claiming details hidden by darkness, blur or occlusion.
PAYLOADS = {
    "HC_ReWiTe_164_tele": diagnosis(
        "白天倾斜取景：近处棕色石雕的衣褶和下半部占据左侧，远处是白灰色建筑的密集窗格，画面下方有树，天空灰白。石雕头部不在画面内。",
        [], (False, False, True, False),
        "缩小显示下未见足以确证的修复性缺陷；细小树叶的柔和程度不能据此归因为原图模糊。保持倾斜构图、石雕衣褶、窗格数量和植被轮廓，不强行锐化。",
        [], "easy", "作为长焦场景中的保守控制：没有明确损伤时不调用工具或新增细节。"),
    "HC_ReWiTe_264_tele": diagnosis(
        "浓密绿篱位于左侧和中央，右侧截入红色汽车的前灯、格栅和部分蓝牌；后方有白车、建筑入口及小标牌，地面是铺砖步道。",
        [degradation("softness", "mild", "local", "绿篱和入口小字", "密集叶片的细小边缘", "汽车灯罩与铺砖的大轮廓", "可见叶片纹理较平，车辆和建筑的大边缘仍清楚；缩小显示限制对最细叶片的判断。")],
        (True, False, True, True),
        "车牌只有一部分在画面内，小标牌不能可靠全文辨认。不得补全车牌、入口文字或细叶数量，保持车灯形状、砖缝和原有裁切。",
        [("T1_OCR", "定位车牌和入口标牌的真实字形区域，保留不确定读数，不补齐画外文字。"),
         ("T4_SEGMENTATION", "分开植被、车辆和建筑，防止叶片处理改变车灯或建筑边界；类别之外的细部保持原状。")],
        "medium", "叶片柔和但车牌、车辆细节敏感，需要限制区域和避免语义补全。"),
    "HC_ReWiTe_260_tele": diagnosis(
        "花坛中有粉红玫瑰、橙花和绿叶，左侧是一辆灰车的车灯与前格栅；上方红边凸面镜反射道路与车辆，镜后有空调风扇，背景还有墙、绿色遮棚和管道。",
        [degradation("softness", "mild", "local", "花叶的细密纹理", "密集绿叶的最细边缘", "花瓣、凸面镜框和车灯的大轮廓", "主体边界清楚，密集叶片局部稍柔；不足以断言全局失焦或某一运动方向。")],
        (False, False, True, True),
        "镜内极小形状不足以确定人脸或五官。凸面镜的弯曲是实际反射特征，不能矫正为普通透视；保留花朵、管道、车灯和原有遮挡。",
        [("T4_SEGMENTATION", "保护花叶与车辆交界，植被区域轻微处理不得改变车灯、镜框和管道；镜内场景不能按猜测重建。")],
        "medium", "复杂花叶和镜面反射需要保护边界，图像本身只支持轻微、保守的处理。"),
    "live_357": diagnosis(
        "橙白衣着人群密集坐在体育场看台，中央有黄色球门立柱，上方有看台遮棚，下方有场地、护栏及场边人员；看台和场边还有广告。",
        [],
        (True, True, True, True),
        "明确有人群，但许多头脸仅几像素；空人脸检测不代表无人。不得新增五官、改变人数、衣服字样、广告内容或球门几何；实际是否长焦无法仅凭图像确认。",
        [("T2_FACE", "只定位能检测到的人脸并保护位置，极小脸允许无检测，不据此生成身份细节。"),
         ("T1_OCR", "定位广告字形和记录不可靠读数，避免恢复时把模糊广告改成猜测内容。"),
         ("T4_SEGMENTATION", "保护人员与场地、建筑的粗区域边界；不把实例检测当作准确人群计数。")],
        "hard", "500乘500原图中的密集小脸和小字存在采样限制，尚未确证额外可修复的模糊；质量标准首先是避免伪造内容。"),
    "commons_002": diagnosis(
        "黑色背景中的斜向霓虹手写体招牌，主体发红，部分发光笔画为黄橙色，上部有少量蓝青色光；没有可见人脸。",
        [degradation("blur", "moderate", "local", "招牌的发光笔画", "部分笔画交会及轮廓重影处", "孤立的较亮短笔画", "笔画边缘较柔，部分有双轮廓或拖曳感；不能可靠判定运动方向，也不能全文读出招牌。")],
        (True, False, False, False),
        "发光晕、饱和色和黑色负空间是霓虹夜景的重要特征。文字不可可靠全文辨认；保持现有笔画，不按预期词语重写，不把背景提亮成日景。",
        [("T1_OCR", "记录发光文字多边形和低置信读数，编辑只能保护实际字形，不能据不确定识别结果重写招牌。")],
        "hard", "重叠发光笔画与未知文字使高强度去模糊容易改变文字内容。"),
    "DPDD_1P0A1734": diagnosis(
        "斜拍的多栏英文科研海报位于玻璃后，左侧有木框、窗和室内外层次，海报上方横跨明亮灯管反射；右栏较清楚，左中栏较虚。",
        [degradation("defocus-blur", "moderate", "local", "海报左中栏", "左侧细小正文和公式", "右侧较清楚的标题与正文", "海报不同栏位的清晰度明显不一致，左中栏文字无法逐字确认；原有焦点梯度可能含拍摄景深。"),
         degradation("reflection", "moderate", "local", "海报上方玻璃反射带", "白亮反射覆盖的字行", "反射带外的右下栏", "亮灯条反射横跨海报，遮挡处没有足够信息推断被遮文字。")],
        (True, False, True, False),
        "保留海报倾斜、栏数、字形、玻璃和暖色室内照明，不补写模糊或被反射遮住的正文。源文件为16位PNG，当前生产canonical是RGB8；原始文件保留，不宣称16位保真。",
        [("T1_OCR", "保留各栏OCR多边形及置信度，对左栏和反射遮挡区只记录不确定文字，不把识别猜测作为修复真值。")],
        "hard", "失焦、斜视和玻璃反射叠加在小字上；必须保留不确定性和实际拍摄景深。"),
    "HC_COZ_175": diagnosis(
        "蓝底白框的中文禁捕告示，左侧有两个红色圆形禁钓图标，两行大白字，右下角有较小署名。大字可见“落实禁捕退捕要求”“严惩非法捕鱼行为”。",
        [degradation("softness", "mild", "global", "文字、图标与边框", "右下小署名及细笔画", "两行大字和红色圆环", "原图489乘261，主要字形仍可辨，小署名和细边缘较柔；不应按常见告示模板补字。")],
        (True, False, False, False),
        "上述大字来自原图可见字形，是观察记录，不是OCR或外部真值。小署名不强行全文转写；保持原有字形、行距、禁钓图标与白框。",
        [("T1_OCR", "核对大字与小署名的定位、真实识别置信度及多边形，保护笔画而不重排或补写。")],
        "medium", "主题明确但小署名敏感，轻微锐化也可能改变汉字笔画。"),
    "RealSR_Nikon_001": diagnosis(
        "黑色电路板上密布白色丝印、孔、元件和细线路，画面上方中部可见倒置的ASUS字样，下方有条码贴纸。",
        [degradation("softness", "moderate", "global", "细丝印和密集线路", "最小字母、条码和细线", "大孔轮廓和较大的ASUS字形", "原图中的细字符和线路较柔，很多小标签不能可靠辨认；线路细部的真实拓扑不能靠猜测补齐。")],
        (True, False, False, False),
        "保持倒置方向、孔位、线路和元件数量，不新增标签或导线。CPU分割类别集不含这些电路元件，不调用分割来猜元件身份。",
        [("T1_OCR", "记录实际可辨的丝印和条码旁的印刷字符，对细标签保留低置信或无识别结果，避免字符被改写；该工具不解码条码。")],
        "hard", "高密度几何细节和小字易被生成式锐化改成虚构电路结构。"),
    "spaq_00002": diagnosis(
        "夜间多层商场步道，左右店铺和发光招牌密集，玻璃栏杆沿透视延伸，右侧有扶梯；下层步道和近处有许多人，上方天空很暗。",
        [degradation("motion-blur", "moderate", "local", "近处和步道中的部分行人", "底部近处运动人物", "静止栏杆与店铺的大轮廓", "部分人物轮廓拖曳和变软，静态结构相对清楚；不是整幅图都需要同等去模糊。"),
         degradation("noise", "mild", "local", "暗天空和灰色结构阴影", "暗天空及暗灰面板", "明亮店面", "暗部有不均匀颗粒或斑驳，混合夜景光源和玻璃反射应保留。")],
        (True, True, True, True),
        "多人脸和广告字很小，部分明亮招牌接近白亮，不能推断不存在的细节。保留人数、广告内容、栏杆透视、扶梯和玻璃反射，维持夜间多色照明。",
        [("T2_FACE", "保护能可靠检测的人脸位置；小脸及运动脸可能为空，不生成未知五官。"),
         ("T1_OCR", "定位店面招牌并保留低置信文本，避免编辑时替换广告内容。"),
         ("T3_DEPTH", "区分近处栏杆、行人、远处步道和店面，限制局部处理而保留透视层次。"),
         ("T4_SEGMENTATION", "保护人员、建筑等已定义类别的边界；玻璃和扶梯可能不在类别集内，不能假定完整覆盖。")],
        "hard", "夜景噪声、局部运动、密集小脸小字和多层玻璃结构同时存在。"),
    "spaq_00934": diagnosis(
        "从观众席后方拍摄的室内礼堂，前景右侧是穿红衣者的后脑和背部，左侧有运动中的模糊人物，中间为排椅，远处舞台有人、红色横幅和投影画面，木墙与灯光偏暖。",
        [degradation("motion-blur", "severe", "local", "左侧运动人物", "左侧人物的脸部和身体轮廓", "静止墙面和天花灯", "左侧人物明显拖曳失去边缘，静止建筑与舞台仍可区分；不能从拖影生成未知身份。"),
         degradation("low-light", "moderate", "local", "前中景座椅和观众", "暗座椅与人物背部", "明亮舞台和天花灯", "前景与舞台亮度差异大，暗座椅细节不足；暖色舞台照明与实际遮挡应保留。")],
        (True, True, True, True),
        "近处主要是后脑而不是可见正脸；舞台人物脸很小。横幅和屏幕小字不能凭常识补写。保留前景遮挡和暖光，不移除观众、不把后脑生成正脸。",
        [("T2_FACE", "只定位舞台或观众中实际可检测的正脸；后脑和重度拖影不能当作可重建身份。"),
         ("T1_OCR", "定位横幅和屏幕文字，记录识别不确定性，避免补写节目或姓名。"),
         ("T3_DEPTH", "区分前景遮挡、座椅和远处舞台，保护实际近远关系。"),
         ("T4_SEGMENTATION", "保护类别集覆盖的人员和建筑粗边界；冻结CPU类别不含椅子，座椅不能依赖分割证据。不得填补被前景遮住的舞台。")],
        "hard", "强局部运动、暗场和小脸小字使保守保护比补全细节更重要。"),
    "realblur_scene094": diagnosis(
        "夜间施工街景，中央偏左有白色工程车，后方有橙色吊装设备；近处有围栏、板材、杆件和砖地，远处灯和标牌对着黑色天空。",
        [degradation("blur", "moderate", "global", "车辆、杆件、地面和标牌", "车前格栅、文字和细杆边缘", "较大的白色车身与橙色设备块面", "多数边缘和文字较软，不能可靠指定模糊运动方向；灯的光晕也可能是正常夜景发光。")],
        (True, False, True, True),
        "未辨认出人脸；未知车标、招牌和杆件连接不能重建为猜测形状。保留夜间暖光、黑天空、栏杆数量、管件关系和原有构图。",
        [("T1_OCR", "定位施工标牌和竖幅的小字，不确定读数不得作为补写依据。"),
         ("T3_DEPTH", "分开近处围挡、车辆及远处街灯，避免去模糊跨越遮挡边界。"),
         ("T4_SEGMENTATION", "保护车辆、建筑和道路等粗区域；细施工杆件并非类别集完整覆盖对象，维持原有几何。")],
        "hard", "全局模糊和施工细杆件、小字组合，锐化强度需受真实可见结构限制。"),
    "commons_007": diagnosis(
        "逆光的两片绿色叶子对着柔和浅色天空，主叶可见细密分叉叶脉、齿状边缘和小缺口，叶柄从左侧弯入，下方还有另一片叶。",
        [], (False, False, True, False),
        "这是正常图控制：没有确证需修复的缺陷。叶片透光和柔和天空是拍摄特征，细叶脉已清楚。保留叶脉拓扑、自然缺口、齿边、叶柄和透光色，避免过度锐化、蜡化或填平缺口。",
        [], "easy", "检测过度处理：不应把逆光、背景柔和或叶缘缺口当作损伤。"),
}

VIEW_SIZES = {
    "HC_ReWiTe_164_tele": (1888, 1334), "HC_ReWiTe_264_tele": (1888, 1334),
    "HC_ReWiTe_260_tele": (1888, 1334), "commons_002": (2048, 1152),
    "spaq_00002": (1824, 1367), "spaq_00934": (1824, 1368),
    "commons_007": (1824, 1368),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    args = parser.parse_args()
    manifest = read_json(args.batch / "manifest.json")
    rows = {r["sample_id"]: r for r in manifest["images"]}
    for sample_id, payload in PAYLOADS.items():
        row = rows[sample_id]
        if sha256_file(Path(row["input_path"])) != row["original_sha256"] or sha256_file(Path(row["canonical_path"])) != row["canonical_sha256"]:
            raise ValueError("Viewed input bytes changed")
        validate_schema("diagnosis.schema.json", payload)
        output = args.batch / "diagnoses" / (sample_id + ".json")
        review_path = args.batch / "visual_reviews" / (sample_id + ".json")
        # Never replace already archived observations with a different payload.
        if output.exists():
            if read_json(output) != payload:
                raise ValueError("Existing diagnosis differs; archive a new review instead")
            continue
        write_json(output, payload)
        view_size = VIEW_SIZES.get(sample_id, (row["width"], row["height"]))
        write_json(review_path, {
            "sample_id": sample_id, "author": "current_local_Work_root_Diagnoser",
            "completed_at": now(), "canonical_individually_viewed": True,
            "input_path": row["input_path"], "original_sha256": row["original_sha256"],
            "canonical_path": row["canonical_path"], "canonical_sha256": row["canonical_sha256"],
            "source_size": [row["width"], row["height"]], "displayed_size": list(view_size),
            "resolution_limitations": "Whole-image view; viewer may reduce large images. No exact unreadable small-text or face-detail claim; no enhancement, crop, GT or model evidence was used.",
            "diagnosis_sha256": sha256_file(output), "schema_validated": True,
            "tool_inference_used": False, "reference_images_read": False,
            "chatgpt_desktop_test": False, "provider_model_ui_id": None,
            "scope": "actual image inspection and JSON authoring in current local Work session; not desktop session dispatch, image editing or an independent Verifier result",
            "observed_content": payload["content"], "uncertainty_and_protection": payload["sensitive"]["notes"],
        })
    print({"actual_viewed_diagnoses_written_or_matched": len(PAYLOADS), "schema_valid": True,
           "tool_inferences": 0, "restorations": 0})


if __name__ == "__main__":
    main()
