/**
 * 选择类的基础零件（下单页用，以后别的页也能用）：可选卡片、分段选择、加减数量、勾选行。
 * 只用设计变量的颜色类；选中 = 主色细边 + 浅底，不加阴影、不用渐变。键盘能操作（radio / checkbox 语义）。
 */
import { Check, Minus, Plus } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const focusRing = "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40";

export interface ChoiceCardProps {
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
  className?: string;
  /** 不能选时为什么（读屏和悬停提示） */
  disabledReason?: string;
}

/** 一张能选的卡片（radio 语义）。 */
export function ChoiceCard({ selected, disabled, onSelect, children, className, disabledReason }: ChoiceCardProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-disabled={disabled || undefined}
      title={disabled ? disabledReason : undefined}
      onClick={() => !disabled && onSelect()}
      className={cn(
        "relative flex w-full flex-col items-start rounded-lg border bg-background p-3.5 text-left transition-colors sm:p-4",
        focusRing,
        selected ? "border-primary bg-highlight/40" : "hover:border-faint",
        disabled && "cursor-not-allowed opacity-45 hover:border-border",
        className,
      )}
    >
      {children}
      {selected ? (
        <span className="absolute top-3 right-3 flex size-4 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Check className="size-3" strokeWidth={3} />
        </span>
      ) : null}
    </button>
  );
}

export interface SegmentOption {
  value: string;
  label: string;
  sub?: string;
  disabled?: boolean;
  disabledReason?: string;
}

export interface SegmentedProps {
  label: string;
  value: string;
  options: SegmentOption[];
  onChange: (value: string) => void;
}

/** 一排里选一个（篇数这种）。 */
export function Segmented({ label, value, options, onChange }: SegmentedProps) {
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-cols-3 gap-2">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            aria-disabled={o.disabled || undefined}
            title={o.disabled ? o.disabledReason : undefined}
            onClick={() => !o.disabled && onChange(o.value)}
            className={cn(
              "flex min-h-11 flex-col items-center justify-center rounded-md border bg-background px-2 py-1.5 text-sm transition-colors",
              focusRing,
              on ? "border-primary bg-highlight/40 font-medium text-foreground" : "text-body hover:border-faint",
              o.disabled && "cursor-not-allowed opacity-45 hover:border-border",
            )}
          >
            <span>{o.label}</span>
            {o.sub ? <span className="text-xs font-normal text-muted-foreground tabular-nums">{o.sub}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export interface StepperProps {
  label: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}

/** 加减数量（再改几轮）。 */
export function Stepper({ label, value, min = 0, max = 5, onChange }: StepperProps) {
  const btn = cn(
    "flex size-8 items-center justify-center rounded-md border bg-background text-body transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40",
    focusRing,
  );
  return (
    <div className="inline-flex items-center gap-2" role="group" aria-label={label}>
      <button type="button" className={btn} aria-label={`${label}减一`} disabled={value <= min} onClick={() => onChange(value - 1)}>
        <Minus className="size-3.5" />
      </button>
      <span className="w-6 text-center text-sm font-medium text-foreground tabular-nums" aria-live="polite">
        {value}
      </span>
      <button type="button" className={btn} aria-label={`${label}加一`} disabled={value >= max} onClick={() => onChange(value + 1)}>
        <Plus className="size-3.5" />
      </button>
    </div>
  );
}

export interface CheckRowProps {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  title: ReactNode;
  note?: ReactNode;
  aside?: ReactNode;
}

/** 一行能勾的（加购）。整行可点。 */
export function CheckRow({ checked, disabled, onChange, title, note, aside }: CheckRowProps) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border bg-background px-3.5 py-3 transition-colors",
        checked ? "border-primary bg-highlight/40" : "hover:border-faint",
        disabled && "cursor-not-allowed opacity-45 hover:border-border",
      )}
    >
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-sm border peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/40",
          checked ? "border-primary bg-primary text-primary-foreground" : "bg-background",
        )}
      >
        {checked ? <Check className="size-3" strokeWidth={3} /> : null}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{title}</span>
        {note ? <span className="text-xs leading-relaxed text-muted-foreground">{note}</span> : null}
      </span>
      {aside ? <span className="shrink-0 text-sm text-body tabular-nums">{aside}</span> : null}
    </label>
  );
}
