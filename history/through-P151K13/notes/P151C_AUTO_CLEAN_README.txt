P151C automatic temporary-DNG cleanup (external Android shell watcher)

Goal: preserve the working XENIUS P151C APK, all RAW/HDR+ processing,
JPEG output and XML settings. Automatically remove only files named
RAW50_REQ*.dng in its own private Android/data/.../files folder.

CLEANUP TRIGGER: The Xenius APP PROCESS stops entirely, and stays stopped
for another 20 seconds. Closing/minimizing its UI does not necessarily
terminate its Android process; in that case cleanup will wait. This is
intentional to avoid interrupting background HDR+ processing.

INITIAL SETUP
1. Download P151C_AUTO_CLEAN.sh to your phone's Download folder.
2. In LADB, enter:
   cp /sdcard/Download/P151C_AUTO_CLEAN.sh /data/local/tmp/p151c_auto_clean.sh && chmod 700 /data/local/tmp/p151c_auto_clean.sh
3. Then enter:
   nohup sh /data/local/tmp/p151c_auto_clean.sh >/dev/null 2>&1 </dev/null &

After the Xenius process exits, the watcher clears its temporary DNGs.
No action is needed after each capture. It DOES NOT survive a phone reboot;
after reboot, repeat only command 3 to restart the watcher.

VIEW CLEANUP LOG:
   tail -n 30 /sdcard/Download/P151C_AUTO_CLEAN_LOG.txt

STOP THE WATCHER:
   kill "$(cat /data/local/tmp/p151c_auto_clean.pid)"

TEST WITHOUT WAITING FOR A SESSION:
   sh /data/local/tmp/p151c_auto_clean.sh --once
   (Deletes debug files only if Xenius is no longer running.)

Not an APK change, not a JPEG-save callback, and not guaranteed to be
permanent under Android's background-process management. No other
images/DNGs/ZIPs/XML files are targeted.