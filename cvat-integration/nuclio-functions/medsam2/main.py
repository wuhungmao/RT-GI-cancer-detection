import base64
import io
import json

import numpy as np
from PIL import Image

from model_handler import ModelHandler, mask_to_rle


def init_context(context):
    context.logger.info("Init context...  0%")
    context.user_data.model = ModelHandler()
    context.logger.info(f"Init context...100% (device: {context.user_data.model.device})")


def handler(context, event):
    context.logger.info("call handler")
    data = event.body
    image = Image.open(io.BytesIO(base64.b64decode(data["image"]))).convert("RGB")

    mask = context.user_data.model.handle(
        np.array(image),
        pos_points=data.get("pos_points") or [],
        neg_points=data.get("neg_points") or [],
        obj_bbox=data.get("obj_bbox") or [],
    )

    return context.Response(
        body=json.dumps(
            {
                "shapes": [
                    {
                        "type": "mask",
                        "points": mask_to_rle(mask),
                        "attributes": [],
                    }
                ]
            }
        ),
        headers={},
        content_type="application/json",
        status_code=200,
    )
