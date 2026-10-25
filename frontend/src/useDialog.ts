import { nextTick, onMounted, onUnmounted, type Ref } from "vue";

/** Keep keyboard navigation inside the current dialog and restore its opener. */
export function useDialog(root: Ref<HTMLElement | null>) {
  const opener = document.activeElement as HTMLElement | null;
  const previousOverflow = document.body.style.overflow;
  function trap(event: KeyboardEvent) {
    if (event.key !== "Tab" || !root.value) return;
    const elements = Array.from(
      root.value.querySelectorAll<HTMLElement>(
        'button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],[tabindex="0"]',
      ),
    ).filter((x) => x.getClientRects().length);
    const first = elements[0],
      last = elements.at(-1);
    if (!first) {
      event.preventDefault();
      return;
    }
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        !root.value.contains(document.activeElement))
    ) {
      event.preventDefault();
      last?.focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === last ||
        !root.value.contains(document.activeElement))
    ) {
      event.preventDefault();
      first.focus();
    }
  }
  onMounted(async () => {
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", trap);
    await nextTick();
    root.value?.querySelector<HTMLElement>("button,input,select")?.focus();
  });
  onUnmounted(() => {
    document.body.style.overflow = previousOverflow;
    document.removeEventListener("keydown", trap);
    if (opener?.isConnected) opener.focus();
  });
}
