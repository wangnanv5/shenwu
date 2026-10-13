from humancursor import SystemCursor

# 初始化桌面系统控制器
cursor = SystemCursor()

# 1. 移动光标到指定屏幕坐标 [x, y]
# steady 参数：True 时轨迹更加稳定平缓；False 时保留更多生理抖动与微小偏差
# cursor.move_to([800, 600], steady=False)

# 2. 移动并在目标点模拟真实点击
# 库会在按键按下（MouseDown）与抬起（MouseUp）之间注入微小的随机延迟
cursor.click_on([800, 600])