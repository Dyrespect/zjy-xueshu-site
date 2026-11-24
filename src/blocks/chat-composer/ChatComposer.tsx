import { ArrowUp, Loader2, Paperclip } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ChatComposerProps {
  onSendText: (text: string) => Promise<void> | void;
  /** 不传就没有传文件按钮 */
  onSendFile?: (file: File) => Promise<void> | void;
  placeholder?: string;
  /** input[type=file] 的 accept */
  accept?: string;
  disabled?: boolean;
  /** 发送按钮上的字（默认只有箭头图标） */
  sendLabel?: string;
}

/** 输入框 + 传文件 + 发送。回车发送（中文输入法选词时的回车不算），Shift+回车换行。 */
export function ChatComposer({ onSendText, onSendFile, placeholder, accept, disabled, sendLabel }: ChatComposerProps) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"text" | "file" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function send() {
    const t = text.trim();
    if (!t || busy) return;
    setBusy("text");
    setText(""); // 先清空，没发出去再放回来（不然慢一拍清空会把客户接着打的字吞掉）
    try {
      await onSendText(t);
    } catch {
      setText((cur) => cur || t);
    } finally {
      setBusy(null);
    }
  }

  async function pick(files: FileList | null) {
    if (!files?.length || !onSendFile) return;
    setBusy("file");
    try {
      for (const f of Array.from(files)) await onSendFile(f);
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="flex items-end gap-2 rounded-2xl border bg-background p-2 focus-within:border-ring">
      {onSendFile ? (
        <>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={accept}
            className="hidden"
            onChange={(e) => void pick(e.target.files)}
            data-testid="composer-file"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="传文件"
            title="传文件"
            disabled={disabled || busy !== null}
            onClick={() => fileRef.current?.click()}
          >
            {busy === "file" ? <Loader2 className="animate-spin" /> : <Paperclip />}
          </Button>
        </>
      ) : null}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        rows={1}
        placeholder={placeholder}
        disabled={disabled}
        aria-label="输入消息"
        className="field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[15px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
      />
      <Button
        type="button"
        size={sendLabel ? "default" : "icon"}
        aria-label="发送"
        disabled={disabled || !text.trim() || busy !== null}
        onClick={() => void send()}
        className={cn(!sendLabel && "rounded-full")}
      >
        {busy === "text" ? <Loader2 className="animate-spin" /> : sendLabel ? sendLabel : <ArrowUp />}
      </Button>
    </div>
  );
}
