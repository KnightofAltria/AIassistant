package cn.csla.mobile

import android.app.Application
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

class LocalApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
    }

    /** Also called by a PDF Activity restored directly into a new process. */
    @Synchronized
    fun startLearning(): JSONObject = JSONObject(Python.getInstance()
        .getModule("mobile_runtime").callAttr("start",
            File(noBackupFilesDir, "learning").absolutePath, KeyVault(this)).toString())
}
