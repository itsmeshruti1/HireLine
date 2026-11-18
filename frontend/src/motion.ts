import { useLayoutEffect } from "react";
import type { RefObject } from "react";
import gsap from "gsap";

// matchMedia reverts inline styles when motion preferences change or a view unmounts.
export function useEntrance(
  ref: RefObject<HTMLElement | null>,
  key: string,
  selector?: string,
) {
  useLayoutEffect(() => {
    const media = gsap.matchMedia();
    media.add(
      "(prefers-reduced-motion: no-preference)",
      () => {
        const targets = selector
          ? ref.current?.querySelectorAll(selector)
          : ref.current;
        if (!targets) return;
        gsap.from(targets, {
          y: 16,
          opacity: 0,
          duration: 0.45,
          stagger: 0.055,
          ease: "power3.out",
          clearProps: "transform,opacity",
        });
      },
      ref,
    );
    return () => media.revert();
  }, [ref, key, selector]);
}
