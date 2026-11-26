from pathlib import Path
import sys
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('xenius-p25a')
p=root/'app/src/main/java/com/xenius/fullresprobe/MainActivity.java'
s=p.read_text()
def replace(old,new):
 global s
 assert s.count(old)==1,(old,s.count(old))
 s=s.replace(old,new)
replace('import android.media.ImageReader;', 'import android.media.ImageReader;\nimport android.media.ExifInterface;')
replace('import android.view.View;', 'import android.view.View;\nimport android.view.OrientationEventListener;\nimport android.view.Surface;')
replace('private static final String TAG = "XENIUS_P25A";', 'private static final String TAG = "XENIUS_P25B";')
replace('private int capturedImages = 0;', '''private int capturedImages = 0;
    private volatile int deviceOrientationDegrees = -1;
    private OrientationEventListener orientationListener;
    private int captureExifOrientation = ExifInterface.ORIENTATION_NORMAL;''')
replace('report.setText("P25A: H85/H35 50 MP RAW protocol probe. Existing GCam unchanged.\\n");', 'report.setText("P25B: H85/H35 50 MP RAW with valid DNG orientation. Existing GCam unchanged.\\n");')
replace('        setContentView(root);\n        worker.post(gate::recoverIfLeftActive);', '''        setContentView(root);
        orientationListener = new OrientationEventListener(this) {
            @Override public void onOrientationChanged(int orientation) {
                if (orientation != OrientationEventListener.ORIENTATION_UNKNOWN) {
                    deviceOrientationDegrees = ((orientation + 45) / 90 * 90) % 360;
                }
            }
        };
        if (orientationListener.canDetectOrientation()) orientationListener.enable();
        worker.post(gate::recoverIfLeftActive);''')
replace('    private void capture50() {', '''    private int computeExifOrientation() {
        // P25A wrote TIFF orientation 9 (unknown) on Vivo V2547A.
        Integer sensorVal = characteristics == null ? null :
                characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION);
        Integer facing = characteristics == null ? null :
                characteristics.get(CameraCharacteristics.LENS_FACING);
        int sensor = sensorVal == null ? 90 : sensorVal;
        int deviceDeg = deviceOrientationDegrees;
        if (deviceDeg < 0) {
            int rotation = getWindowManager().getDefaultDisplay().getRotation();
            switch (rotation) {
                case Surface.ROTATION_90: deviceDeg = 90; break;
                case Surface.ROTATION_180: deviceDeg = 180; break;
                case Surface.ROTATION_270: deviceDeg = 270; break;
                default: deviceDeg = 0;
            }
        }
        int degrees = facing != null && facing == CameraCharacteristics.LENS_FACING_FRONT
                ? (sensor + deviceDeg) % 360
                : (sensor - deviceDeg + 360) % 360;
        int exif;
        switch (degrees) {
            case 90: exif = ExifInterface.ORIENTATION_ROTATE_90; break;
            case 180: exif = ExifInterface.ORIENTATION_ROTATE_180; break;
            case 270: exif = ExifInterface.ORIENTATION_ROTATE_270; break;
            default: exif = ExifInterface.ORIENTATION_NORMAL;
        }
        info("DNG_ORIENTATION", "camera=" + activeCameraId + " device=" + deviceDeg
                + " sensor=" + sensor + " rotation=" + degrees + " exif=" + exif);
        return exif;
    }

    private void capture50() {''')
replace('            lastStillResult.set(null);\n            CaptureRequest.Builder b = newBuilder(CameraDevice.TEMPLATE_STILL_CAPTURE);', '''            lastStillResult.set(null);
            captureExifOrientation = computeExifOrientation();
            CaptureRequest.Builder b = newBuilder(CameraDevice.TEMPLATE_STILL_CAPTURE);''')
replace('                    dng.writeImage(out, image);', '''                    dng.setOrientation(captureExifOrientation);
                    dng.writeImage(out, image);''')
replace('    @Override protected void onDestroy() {\n        worker.post(this::closeCamera);', '''    @Override protected void onDestroy() {
        if (orientationListener != null) orientationListener.disable();
        worker.post(this::closeCamera);''')
p.write_text(s)
p=root/'app/build.gradle';s=p.read_text();assert 'versionCode 251' in s;s=s.replace('versionCode 251','versionCode 252').replace("versionName 'P25A-H85-probe'","versionName 'P25B-auto-orientation'");p.write_text(s)
p=root/'app/src/main/AndroidManifest.xml';s=p.read_text();assert 'Xenius FullRes P25A' in s;s=s.replace('Xenius FullRes P25A','Xenius FullRes P25B');p.write_text(s)
print('P25B orientation patch applied')
