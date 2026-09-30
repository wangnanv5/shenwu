import argparse
import time

import cv2
import numpy as np
import mss


def parse_args():
    parser = argparse.ArgumentParser(
        description="OpenCV 实时屏幕模板匹配，显示图标 bbox"
    )
    parser.add_argument(
        "--icon",
        required=True,
        help="小图标路径，例如 icon.png",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.82,
        help="匹配阈值，范围 0~1，越大越严格",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="mss 显示器索引：0=所有屏幕, 1=第一个屏幕, 2=第二个屏幕...",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=15.0,
        help="最大帧率，降低 CPU 占用",
    )
    parser.add_argument(
        "--gray",
        action="store_true",
        help="使用灰度匹配，速度更快，但可能受颜色变化影响",
    )
    parser.add_argument(
        "--multiscale",
        action="store_true",
        help="启用多尺度匹配，适合图标大小可能变化的情况",
    )
    parser.add_argument(
        "--min-scale",
        type=float,
        default=0.6,
        help="多尺度最小缩放比例",
    )
    parser.add_argument(
        "--max-scale",
        type=float,
        default=1.4,
        help="多尺度最大缩放比例",
    )
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="多尺度缩放步长",
    )
    parser.add_argument(
        "--display-scale",
        type=float,
        default=1.0,
        help="预览窗口缩放，例如 0.5 表示缩小一半显示",
    )
    parser.add_argument(
        "--no-mask",
        action="store_true",
        help="即使 icon 有透明通道，也不使用 mask",
    )
    return parser.parse_args()


def load_icon(path):
    """
    读取图标。
    如果图标是带透明通道的 PNG，会尝试生成 mask。
    """
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"无法读取图标: {path}")

    if img.ndim == 2:
        return img, None

    channels = img.shape[2]

    if channels == 1:
        return img, None

    if channels == 2:
        return img[:, :, 0], None

    if channels == 4:
        alpha = img[:, :, 3]
        bgr = img[:, :, :3].copy()

        # 将透明通道二值化，作为模板匹配 mask
        alpha_bin = (alpha > 128).astype(np.uint8) * 255

        if np.count_nonzero(alpha_bin) == 0:
            raise ValueError("图标几乎全透明，无法用于模板匹配")

        # 只有存在明显透明区域时才启用 mask
        if np.any(alpha <= 10):
            mask = cv2.merge([alpha_bin, alpha_bin, alpha_bin])
        else:
            mask = None

        return bgr, mask

    if channels == 3:
        return img, None

    # 兜底：强转 BGR
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), None


def prepare(frame, icon, mask, gray):
    """
    是否转灰度。
    """
    if not gray:
        return frame, icon, mask

    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if icon.ndim == 3:
        icon = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)

    if mask is not None and mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

    return frame, icon, mask


def match_template(image, templ, mask, threshold):
    """
    单尺度模板匹配。
    返回:
        {
            "bbox": (x, y, w, h),
            "score": score,
            "scale": 1.0
        }
    或 None
    """
    th, tw = templ.shape[:2]
    ih, iw = image.shape[:2]

    if th > ih or tw > iw:
        return None

    use_mask = mask is not None

    # OpenCV 的 matchTemplate 对 mask 支持有限：
    # 一般只在 TM_SQDIFF / TM_CCORR_NORMED 下可用。
    method = cv2.TM_CCORR_NORMED if use_mask else cv2.TM_CCOEFF_NORMED

    try:
        if use_mask:
            result = cv2.matchTemplate(image, templ, method, None, mask)
        else:
            result = cv2.matchTemplate(image, templ, method)
    except cv2.error:
        # 某些 OpenCV 版本或输入组合可能不支持 mask，回退到无 mask
        if use_mask:
            result = cv2.matchTemplate(image, templ, cv2.TM_CCOEFF_NORMED)
            method = cv2.TM_CCOEFF_NORMED
        else:
            raise

    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return None

    h, w = templ.shape[:2]
    x, y = int(max_loc[0]), int(max_loc[1])

    return {
        "bbox": (x, y, w, h),
        "score": float(max_val),
        "scale": 1.0,
    }


def find_best_match(frame, icon, mask, args):
    """
    单尺度或多尺度匹配。
    """
    frame_p, icon_p, mask_p = prepare(frame, icon, mask, args.gray)

    if not args.multiscale:
        return match_template(frame_p, icon_p, mask_p, args.threshold)

    best = None

    scales = np.arange(
        args.min_scale,
        args.max_scale + 1e-6,
        args.scale_step,
    )

    for s in scales:
        h = int(round(icon.shape[0] * s))
        w = int(round(icon.shape[1] * s))

        if h < 8 or w < 8:
            continue

        if h > frame_p.shape[0] or w > frame_p.shape[1]:
            continue

        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
        resized_icon = cv2.resize(icon_p, (w, h), interpolation=interp)

        resized_mask = None
        if mask_p is not None:
            resized_mask = cv2.resize(
                mask_p,
                (w, h),
                interpolation=cv2.INTER_NEAREST,
            )

        candidate = match_template(
            frame_p,
            resized_icon,
            resized_mask,
            args.threshold,
        )

        if candidate is None:
            continue

        candidate["scale"] = float(s)

        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best


def main():
    args = parse_args()

    if args.scale_step <= 0:
        raise ValueError("--scale-step 必须大于 0")

    if args.min_scale > args.max_scale:
        raise ValueError("--min-scale 不能大于 --max-scale")

    icon, mask = load_icon(args.icon)

    if args.no_mask:
        mask = None

    with mss.mss() as sct:
        if args.monitor < 0 or args.monitor >= len(sct.monitors):
            print(
                f"错误: monitor={args.monitor} 无效，"
                f"可用索引: 0..{len(sct.monitors) - 1}"
            )
            return

        monitor = sct.monitors[args.monitor]

        window_name = "OpenCV Screen Template Matching - Press q to quit"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        interval = 1.0 / args.fps if args.fps > 0 else 0.0

        while True:
            t0 = time.time()

            # 截取屏幕
            shot = np.asarray(sct.grab(monitor))

            # mss 默认是 BGRA，转成 OpenCV 常用 BGR
            frame = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

            # 匹配
            match = find_best_match(frame, icon, mask, args)

            if match is not None:
                x, y, w, h = match["bbox"]
                score = match["score"]
                scale = match["scale"]

                # 局部坐标：相对于当前截取画面
                # 全局坐标：加上当前 monitor 的 left/top
                global_x = x + monitor["left"]
                global_y = y + monitor["top"]

                # 画 bbox
                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2,
                )

                # 画分数标签
                label = f"{score:.2f}"
                if args.multiscale:
                    label += f" x{scale:.2f}"

                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                thickness = 2

                (tw, th), baseline = cv2.getTextSize(
                    label,
                    font,
                    font_scale,
                    thickness,
                )

                label_y = max(y - 10, th + 10)

                cv2.rectangle(
                    frame,
                    (x, label_y - th - 8),
                    (x + tw + 8, label_y + baseline),
                    (0, 255, 0),
                    -1,
                )

                cv2.putText(
                    frame,
                    label,
                    (x + 4, label_y),
                    font,
                    font_scale,
                    (0, 0, 0),
                    thickness,
                )

                print(
                    f"\rlocal bbox=(x={x}, y={y}, w={w}, h={h}) | "
                    f"global top-left=({global_x}, {global_y}) | "
                    f"score={score:.3f} | scale={scale:.2f}   ",
                    end="",
                    flush=True,
                )
            else:
                print(
                    f"\rno match | threshold={args.threshold:.2f}            ",
                    end="",
                    flush=True,
                )

            # 预览缩放
            if args.display_scale != 1.0:
                display_frame = cv2.resize(
                    frame,
                    None,
                    fx=args.display_scale,
                    fy=args.display_scale,
                )
            else:
                display_frame = frame

            cv2.imshow(window_name, display_frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            if key == ord("s"):
                save_path = f"icon_match_{int(time.time())}.png"
                cv2.imwrite(save_path, frame)
                print(f"\nsaved: {save_path}")

            dt = time.time() - t0
            if interval > dt:
                time.sleep(interval - dt)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()