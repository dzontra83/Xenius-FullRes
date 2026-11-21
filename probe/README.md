# vivo full-size RAW probe (from RawR)

Unmodified copy of RawR's `tools/vivo_fullres_probe` (GPL-3.0, see LICENSE-RAWR), built by
`.github/workflows/probe.yml` on the `probe-build` branch. The workflow commits the debug APK to
`probe/out/` (and the build log to `probe/out/build.log`).

Package id `android.camera.cts` (default): the vivo HAL honours `vivo.control.forceSensorMode` only for
allow-listed packages.

Use (LADB / adb shell):

    am start -n android.camera.cts/com.rawr.probe.ProbeActivity --es mode dump
    am start -S -W -n android.camera.cts/com.rawr.probe.ProbeActivity --es mode capture --es cam 3 --ei row <N> --ei w 8160 --ei h 6128 --ei frames 1
    cp -r /sdcard/Android/data/android.camera.cts/files /sdcard/Download/probe

Goal here: find a camera 3 (main) 50 MP sensor mode that delivers the native quad layout (not remosaiced).
