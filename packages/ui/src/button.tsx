import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./cn";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] text-sm font-medium transition-colors " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 disabled:pointer-events-none disabled:opacity-50 " +
    "[&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:bg-accent-strong",
        secondary: "bg-surface-2 text-text hover:bg-surface-3 border border-border",
        ghost: "text-muted hover:text-text hover:bg-surface-2",
        outline: "border border-border-strong text-text hover:bg-surface-2",
        danger: "bg-danger/15 text-danger hover:bg-danger/25",
        link: "text-accent underline-offset-4 hover:underline px-0",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-9 px-3.5", lg: "h-11 px-5 text-[15px]", icon: "size-8 p-0" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = "Button";
