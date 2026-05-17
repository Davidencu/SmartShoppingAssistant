"use client";

import { forwardRef, useImperativeHandle, useRef, useState, useEffect, KeyboardEvent } from "react";
import { Send, Loader2, X, ImagePlus } from "lucide-react";
import { compressImage } from "@/lib/imageCompressor";

interface Props {
  onSend: (text: string, imageBase64?: string) => void;
  disabled?: boolean;
}

export interface ChatInputHandle {
  prefill: (text: string) => void;
}

const ChatInput = forwardRef<ChatInputHandle, Props>(function ChatInput(
  { onSend, disabled = false },
  ref
) {
  const [text, setText] = useState("");
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [compressing, setCompressing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    prefill(value: string) {
      setText(value);
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(value.length, value.length);
      });
    },
  }));

  // Auto-resize textarea to fit content, capped at 200px
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleFile = async (file: File) => {
    if (!file.type.startsWith("image/")) return;
    setCompressing(true);
    try {
      const b64 = await compressImage(file);
      setImageBase64(b64);
      setPreviewUrl(URL.createObjectURL(file));
    } catch {
      // silently ignore compression errors
    } finally {
      setCompressing(false);
    }
  };

  const clearImage = () => {
    setImageBase64(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed && !imageBase64) return;
    onSend(trimmed, imageBase64 ?? undefined);
    setText("");
    clearImage();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && !compressing) handleSend();
    }
  };

  const isBusy = disabled || compressing;

  return (
    <div className="border dark:border-gray-700 rounded-2xl bg-white dark:bg-gray-800 shadow-sm overflow-hidden">
      {/* Image preview strip */}
      {previewUrl && (
        <div className="px-4 pt-4 flex items-center gap-3">
          <div className="relative w-16 h-16 rounded-lg overflow-hidden border dark:border-gray-600 shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={previewUrl} alt="Preview" className="w-full h-full object-cover" />
            <button
              onClick={clearImage}
              aria-label="Remove image"
              className="absolute top-1 right-1 bg-black/60 rounded-full p-0.5 hover:bg-black/80 transition-colors"
            >
              <X className="w-3 h-3 text-white" />
            </button>
          </div>
          <span className="text-sm text-gray-400 dark:text-gray-500">Image attached</span>
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-3 p-4">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What are you looking for?"
          disabled={isBusy}
          rows={1}
          className="flex-1 resize-none bg-transparent text-base text-gray-900 dark:text-gray-100
            placeholder-gray-400 dark:placeholder-gray-500 outline-none
            overflow-y-auto disabled:opacity-50"
          style={{ lineHeight: "1.6", maxHeight: "200px" }}
        />

        {/* Image upload button */}
        <button
          type="button"
          aria-label="Attach image"
          onClick={() => fileRef.current?.click()}
          disabled={isBusy}
          className="w-10 h-10 flex items-center justify-center rounded-full border border-dashed
            border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500
            hover:border-indigo-400 hover:text-indigo-500 transition-colors disabled:opacity-40 shrink-0"
        >
          {compressing ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <ImagePlus className="w-5 h-5" />
          )}
        </button>

        {/* Send button */}
        <button
          type="button"
          aria-label="Send message"
          onClick={handleSend}
          disabled={isBusy || (!text.trim() && !imageBase64)}
          className="w-10 h-10 flex items-center justify-center rounded-full bg-indigo-600
            text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors shrink-0"
        >
          {disabled ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Send className="w-5 h-5" />
          )}
        </button>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
    </div>
  );
});

export default ChatInput;
