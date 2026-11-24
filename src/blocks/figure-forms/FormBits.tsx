import { useId, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

/** 一个表单项：标签 + 输入 + 提示。选填的在标签后面写「（选填）」 */
export function Field({
  label,
  optional,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  optional?: boolean;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
        {label}
        {optional ? <span className="font-normal text-muted-foreground">（选填）</span> : null}
      </Label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** 蜜罐：页面上看不见，人不会填；机器人填了，后端照常回「收到了」但不入库 */
export function Honeypot({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="text"
      name="website"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      tabIndex={-1}
      autoComplete="off"
      aria-hidden="true"
      className="pointer-events-none absolute -left-[10000px] h-px w-px opacity-0"
    />
  );
}

/** 选一张图：原生文件框藏起来，显示一个按钮和选中的文件名 */
export function ImagePicker({
  file,
  onChange,
  maxMb,
  onTooLarge,
  buttonText = "选一张图",
}: {
  file: File | null;
  onChange: (f: File | null) => void;
  maxMb: number;
  onTooLarge: (msg: string) => void;
  buttonText?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const id = useId();
  return (
    <div className="flex min-w-0 items-center gap-3">
      <input
        id={id}
        ref={ref}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          e.target.value = "";
          if (f && f.size > maxMb * 1024 * 1024) {
            onTooLarge(`图片不能超过 ${maxMb}MB`);
            return;
          }
          onChange(f);
        }}
      />
      <Button type="button" variant="outline" size="sm" onClick={() => ref.current?.click()}>
        {file ? "换一张" : buttonText}
      </Button>
      {file ? (
        <span className="flex min-w-0 items-center gap-2 text-sm text-body">
          <span className="truncate">{file.name}</span>
          <button type="button" className="shrink-0 text-muted-foreground hover:text-foreground" onClick={() => onChange(null)}>
            去掉
          </button>
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">png、jpg，{maxMb}MB 以内</span>
      )}
    </div>
  );
}

export function FormError({ message }: { message: string }) {
  return message ? (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  ) : null;
}

export function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "没提交成功，请稍后再试";
}
