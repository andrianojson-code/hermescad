"""Headless Blender (bpy module) with the Hermes3D bridge on :9877 - for tests."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_addon"))
import bpy
from hermes3d import bridge
b = bridge.start(port=int(os.environ.get("HERMES3D_PORT", "9877")), use_timer="manual")
while True:  # main-thread pump, like Blender's timer in the GUI
    b.pump()
    time.sleep(0.02)
