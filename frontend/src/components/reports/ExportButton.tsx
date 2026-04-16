/**
 * C15 ExportButton — 点击触发 Word 导出 + 进度条 + 重试
 *
 * 状态机:idle → running → done | failed
 * - idle:按钮可点
 * - running:显示进度条(订阅 SSE export_progress)
 * - done:下载按钮(自动触发一次下载)
 * - failed:显示错误 + 重试按钮
 *
 * SSE 消息契约(design D9):
 *   event: export_progress
 *   data: { job_id, phase: rendering|writing|done|failed, progress, message }
 */
import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "../../services/api";

type Phase = "idle" | "running" | "done" | "failed";

interface ExportProgressEvent {
  job_id: number;
  phase: "rendering" | "writing" | "done" | "failed";
  progress: number;
  message: string;
}

interface Props {
  projectId: number | string;
  version: number | string;
}

export function ExportButton({ projectId, version }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const start = async () => {
    setPhase("running");
    setProgress(0);
    setMessage("提交任务");
    try {
      const { job_id } = await api.startExport(projectId, version);
      setJobId(job_id);
      subscribeSse(job_id);
    } catch (err) {
      setPhase("failed");
      setMessage(
        err instanceof ApiError ? `启动失败 (${err.status})` : "启动失败",
      );
    }
  };

  const subscribeSse = (job_id: number) => {
    // 复用既有 SSE endpoint
    const url = api.analysisEventsUrl(projectId);
    const es = new EventSource(url, { withCredentials: false });
    esRef.current = es;

    es.addEventListener("export_progress", (e: MessageEvent) => {
      try {
        const data: ExportProgressEvent = JSON.parse(e.data);
        if (data.job_id !== job_id) return;
        setProgress(data.progress);
        setMessage(data.message);
        if (data.phase === "done") {
          setPhase("done");
          es.close();
          // 自动触发下载
          window.open(api.downloadExportUrl(job_id), "_blank");
        } else if (data.phase === "failed") {
          setPhase("failed");
          es.close();
        }
      } catch {
        // ignore parse errors
      }
    });
    es.onerror = () => {
      // 连接错误不立即切 failed(可能是重连);3 秒后若未 done/failed 再切
      // 这里简单处理:保留 running 态,用户可手动取消
    };
  };

  const retry = () => {
    esRef.current?.close();
    setJobId(null);
    void start();
  };

  if (phase === "idle") {
    return (
      <button
        type="button"
        className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
        onClick={start}
      >
        导出 Word
      </button>
    );
  }

  if (phase === "running") {
    return (
      <div className="flex items-center gap-2">
        <div className="w-40 h-2 bg-gray-200 rounded overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
        <span className="text-xs text-gray-500">{message}</span>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-green-600 text-sm">✓ 已生成</span>
        {jobId !== null && (
          <a
            href={api.downloadExportUrl(jobId)}
            className="px-3 py-1 bg-green-600 text-white rounded"
            target="_blank"
            rel="noreferrer"
          >
            重新下载
          </a>
        )}
      </div>
    );
  }

  // failed
  return (
    <div className="flex items-center gap-2">
      <span className="text-red-600 text-sm">✗ {message || "生成失败"}</span>
      <button
        type="button"
        className="px-3 py-1 bg-orange-500 text-white rounded hover:bg-orange-600"
        onClick={retry}
      >
        重试
      </button>
    </div>
  );
}

export default ExportButton;
