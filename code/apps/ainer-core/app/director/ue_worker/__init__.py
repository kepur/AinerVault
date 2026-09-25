"""Unreal Engine 适配（V1 预埋、不启用：feature_flags.ue_enabled=false）。

协议 ＋ 烘焙数据 → UE 指令（生成物体、Sequencer 轨道、机位剪辑、Movie Render Queue）。
翻译和脚本生成是纯函数，关着开关也能跑（dry-run、离线调试）；真正连 UE 执行要开关打开。
"""
