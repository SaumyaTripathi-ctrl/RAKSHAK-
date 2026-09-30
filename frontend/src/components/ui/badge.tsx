import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        safe: "border-green-600/40 bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200",
        warn: "border-orange-600/50 bg-orange-100 text-orange-950 dark:bg-orange-950 dark:text-orange-100",
        crit: "border-red-600/50 bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
        sim: "border-dashed border-secondary/60 bg-secondary/10 text-secondary",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
