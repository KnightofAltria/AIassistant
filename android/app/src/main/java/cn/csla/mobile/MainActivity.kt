package cn.csla.mobile

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.ClipData
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.*
import android.widget.*
import android.window.OnBackInvokedDispatcher
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var status: TextView
    private val worker = Executors.newSingleThreadExecutor()
    private var base = ""
    private var chooser: ValueCallback<Array<Uri>>? = null
    private var pendingDownload: String? = null
    private var downloadMime = "application/octet-stream"
    private var restorePath = "/"
    private val runtime get() = Python.getInstance().getModule("mobile_runtime")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        restorePath = savedInstanceState?.getString("view_path")?.takeIf { it.startsWith("/?") || it == "/" } ?: "/"
        pendingDownload = savedInstanceState?.getString("pending_download")
            ?.takeIf { it.startsWith("/api/") && !it.contains("\r") && !it.contains("\n") }
        downloadMime = savedInstanceState?.getString("download_mime") ?: "application/octet-stream"
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        column.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        val bar = LinearLayout(this).apply { setBackgroundColor(Color.rgb(240, 245, 250)) }
        fun button(text: String, action: () -> Unit) {
            bar.addView(Button(this).apply { this.text = text; setOnClickListener { action() } })
        }
        button("返回") { goBack() }
        button("目录") {
            if (base.isNotEmpty()) web.evaluateJavascript(
                "document.getElementById('sidebar').classList.toggle('mobile-open')", null)
        }
        button("设置") {
            if (base.isNotEmpty()) web.evaluateJavascript(
                "document.getElementById('btn-settings').click()", null)
        }
        status = TextView(this).apply {
            text = "正在启动手机本地学习库…"
            setPadding(16, 10, 16, 10)
        }
        web = WebView(this)
        column.addView(bar)
        column.addView(status)
        column.addView(web, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(column)
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT) { goBack() }
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true // SAF-selected files only.
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString += " CSLAAndroid/1"
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                return navigate(request.url)
            }
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val uri = request.url
                if (isLocal(uri) || uri.scheme in listOf("data", "blob", "about")) return null
                return WebResourceResponse("text/plain", "utf-8", 403, "Blocked", emptyMap(),
                    ByteArrayInputStream(ByteArray(0)))
            }
            override fun onPageFinished(view: WebView, url: String) {
                status.text = "资料与记录仅存此手机 · AI 生成需要联网"
            }
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    status.text = "本地页面加载失败，点击重试"
                    status.setOnClickListener { if (base.isNotEmpty()) web.loadUrl(base) else launchLocal() }
                }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null)
                chooser = callback
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    val types = acceptedMimeTypes(params.acceptTypes)
                    type = if (types.size == 1) types[0] else "*/*"
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                    if (types.size > 1) putExtra(Intent.EXTRA_MIME_TYPES, types)
                }
                return try { startActivityForResult(intent, 100); true }
                catch (_: Exception) { chooser = null; callback.onReceiveValue(null); false }
            }
            override fun onJsAlert(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity).setMessage(message)
                    .setPositiveButton("确定") { _, _ -> result.confirm() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }
            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity).setMessage(message)
                    .setPositiveButton("确定") { _, _ -> result.confirm() }
                    .setNegativeButton("取消") { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }
            override fun onJsPrompt(view: WebView, url: String, message: String,
                defaultValue: String?, result: JsPromptResult): Boolean {
                if (!isLocal(Uri.parse(url))) { result.cancel(); return true }
                val input = EditText(this@MainActivity).apply {
                    setText(defaultValue ?: "")
                    inputType = android.text.InputType.TYPE_CLASS_TEXT or
                        android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE or
                        android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                    minLines = if (message.contains("大纲")) 4 else 1
                    maxLines = 10
                    setPadding(24, 16, 24, 16)
                }
                AlertDialog.Builder(this@MainActivity).setMessage(message).setView(input)
                    .setPositiveButton("保存") { _, _ -> result.confirm(input.text.toString()) }
                    .setNegativeButton("取消") { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }
        }
        web.setDownloadListener { url, _, disposition, mime, _ ->
            saveDocument(url, URLUtil.guessFileName(url, disposition, mime), mime ?: "application/octet-stream")
        }
        val webVersion = WebView.getCurrentWebViewPackage()?.versionName
            ?.substringBefore('.')?.toIntOrNull() ?: 0
        if (webVersion in 1..99) {
            status.text = "请先更新 Android System WebView，再重启应用。"
            return
        }
        launchLocal()
    }

    private fun launchLocal() {
        worker.execute {
            try {
                val info = (application as LocalApplication).startLearning()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    base = info.getString("url")
                    CookieManager.getInstance().setCookie(base, info.getString("cookie")) {
                        web.loadUrl(base + restorePath)
                    }
                }
            } catch (_: Exception) {
                runOnUiThread {
                    status.text = "本地学习库启动失败，点击重试。请检查可用存储空间。"
                    status.setOnClickListener { launchLocal() }
                }
            }
        }
    }

    private fun isLocal(uri: Uri): Boolean {
        if (base.isEmpty()) return false
        val origin = Uri.parse(base)
        return uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == origin.port
    }

    private fun acceptedMimeTypes(accept: Array<String>): Array<String> {
        val extensions = mapOf(".pdf" to "application/pdf",
            ".docx" to "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt" to "text/plain", ".md" to "text/plain", ".markdown" to "text/plain",
            ".csv" to "text/csv", ".json" to "application/json",
            ".png" to "image/png", ".jpg" to "image/jpeg", ".jpeg" to "image/jpeg")
        return accept.flatMap { it.split(",") }.mapNotNull {
            val value = it.trim().lowercase()
            extensions[value] ?: value.takeIf { item -> item.contains("/") }
        }.distinct().ifEmpty { listOf("*/*") }.toTypedArray()
    }

    private fun navigate(uri: Uri): Boolean {
        if (isLocal(uri)) {
            if (uri.path == "/api/export/report") {
                saveDocument(uri.toString(), "CSLA-学习报告.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                return true
            }
            val match = Regex("^/api/(?:mobile/pdf|materials)/([\\w-]+)(?:/source)?$").matchEntire(uri.path ?: "")
            if (match != null && (uri.path!!.contains("/mobile/pdf/") || uri.path!!.endsWith("/source"))) {
                if (uri.getQueryParameter("download") == "1") {
                    val id = match.groupValues[1]
                    worker.execute {
                        try {
                            val info = JSONObject(runtime.callAttr("source_info", id).toString())
                            val name = info.getString("name")
                            val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(
                                name.substringAfterLast('.').lowercase()) ?: "application/octet-stream"
                            runOnUiThread { saveDocument(uri.toString(), name, mime) }
                        } catch (_: Exception) { runOnUiThread { message("源文件不存在") } }
                    }
                } else {
                    val id = match.groupValues[1]
                    worker.execute {
                        try {
                            val info = JSONObject(runtime.callAttr("source_info", id).toString())
                            runOnUiThread {
                                if (info.getBoolean("pdf")) {
                                    val page = Regex("page=(\\d+)").find(uri.fragment ?: "")?.groupValues?.get(1)?.toIntOrNull()
                                        ?: uri.getQueryParameter("page")?.toIntOrNull() ?: 1
                                    startActivity(Intent(this, PdfActivity::class.java)
                                        .putExtra("material_id", id).putExtra("page", page))
                                } else web.loadUrl("$base/?view=reader&id=$id")
                            }
                        } catch (_: Exception) { runOnUiThread { message("源文件不存在或不能读取") } }
                    }
                }
                return true
            }
            return false
        }
        if (uri.scheme in listOf("https", "http")) {
            try { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
            catch (_: Exception) { message("没有可用的浏览器") }
        }
        return true
    }

    private fun saveDocument(url: String, filename: String, mime: String) {
        if (!isLocal(Uri.parse(url))) { message("仅支持导出本地学习文件"); return }
        if (pendingDownload != null) { message("请先完成当前导出"); return }
        pendingDownload = Uri.parse(url).encodedPath + (Uri.parse(url).encodedQuery?.let { "?$it" } ?: "")
        downloadMime = mime
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = mime
            putExtra(Intent.EXTRA_TITLE, filename.replace(Regex("[/\\\\]"), "_"))
        }
        try { startActivityForResult(intent, 101) }
        catch (_: Exception) { pendingDownload = null; message("系统文件保存器不可用") }
    }

    @Deprecated("Android platform callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 100) {
            val result = if (resultCode == RESULT_OK) WebChromeClient.FileChooserParams.parseResult(resultCode, data) else null
            chooser?.onReceiveValue(result)
            chooser = null
        } else if (requestCode == 101) {
            val url = pendingDownload
            pendingDownload = null
            val destination = data?.data
            if (resultCode != RESULT_OK || destination == null || url == null) return
            val mime = downloadMime
            worker.execute {
                var connection: HttpURLConnection? = null
                try {
                    val info = (application as LocalApplication).startLearning()
                    connection = URL(info.getString("url") + url).openConnection() as HttpURLConnection
                    connection.instanceFollowRedirects = false
                    connection.connectTimeout = 15000
                    connection.readTimeout = 30000
                    connection.setRequestProperty("Cookie", info.getString("cookie").substringBefore(';'))
                    require(connection.responseCode == 200)
                    connection.inputStream.use { input ->
                        contentResolver.openOutputStream(destination, "wt")!!.use { output ->
                            val buffer = ByteArray(65536)
                            var total = 0L
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                total += count
                                require(total <= 64L * 1024 * 1024)
                                output.write(buffer, 0, count)
                            }
                        }
                    }
                    runOnUiThread {
                        if (isFinishing || isDestroyed) return@runOnUiThread
                        AlertDialog.Builder(this).setMessage("已导出到所选位置")
                            .setPositiveButton("完成", null)
                            .setNeutralButton("分享") { _, _ ->
                                val share = Intent(Intent.ACTION_SEND).apply {
                                    type = mime
                                    putExtra(Intent.EXTRA_STREAM, destination)
                                    clipData = ClipData.newUri(contentResolver, "学习文件", destination)
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                }
                                try { startActivity(Intent.createChooser(share, "分享学习文件")) }
                                catch (_: Exception) { message("没有可用的分享应用") }
                            }.show()
                    }
                } catch (_: Exception) {
                    runOnUiThread { message("导出失败，请删除未完成文件后重试") }
                } finally { connection?.disconnect() }
            }
        }
    }

    private fun message(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()

    private fun goBack() {
        web.evaluateJavascript(
            "typeof window.handleAndroidBack==='function' ? window.handleAndroidBack() : null"
        ) { handled ->
            when (handled) {
                "true" -> Unit
                "false" -> finish()
                else -> if (web.canGoBack()) web.goBack() else finish()
            }
        }
    }
    @Deprecated("Android platform callback")
    override fun onBackPressed() { goBack() }
    override fun onSaveInstanceState(outState: Bundle) {
        if (::web.isInitialized && isLocal(Uri.parse(web.url ?: ""))) {
            val uri = Uri.parse(web.url)
            outState.putString("view_path", uri.encodedPath + (uri.encodedQuery?.let { "?$it" } ?: ""))
        }
        outState.putString("pending_download", pendingDownload)
        outState.putString("download_mime", downloadMime)
        super.onSaveInstanceState(outState)
    }
    override fun onStart() {
        super.onStart()
        runtime.callAttr("set_foreground", true)
        if (::web.isInitialized) web.onResume()
    }
    override fun onStop() {
        runtime.callAttr("set_foreground", false)
        if (::web.isInitialized) web.onPause()
        super.onStop()
    }
    override fun onDestroy() {
        chooser?.onReceiveValue(null)
        web.destroy()
        worker.shutdown()
        super.onDestroy()
    }
}
