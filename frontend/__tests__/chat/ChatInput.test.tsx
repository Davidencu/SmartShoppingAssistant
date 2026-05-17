import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatInput from "@/components/chat/ChatInput";
import * as imageCompressor from "@/lib/imageCompressor";

jest.mock("@/lib/imageCompressor");

beforeEach(() => {
  jest.clearAllMocks();
  URL.createObjectURL = jest.fn(() => "blob:preview-url");
  URL.revokeObjectURL = jest.fn();
});

describe("ChatInput", () => {
  it("renders the text area and image upload button", () => {
    render(<ChatInput onSend={jest.fn()} />);
    expect(screen.getByPlaceholderText(/what are you looking for/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /attach image/i })).toBeInTheDocument();
  });

  it("send button is disabled when input is empty", () => {
    render(<ChatInput onSend={jest.fn()} />);
    expect(screen.getByRole("button", { name: /send message/i })).toBeDisabled();
  });

  it("send button enables when text is typed", async () => {
    render(<ChatInput onSend={jest.fn()} />);
    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "I need a laptop"
    );
    expect(screen.getByRole("button", { name: /send message/i })).not.toBeDisabled();
  });

  it("calls onSend with text and clears input on button click", async () => {
    const onSend = jest.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByPlaceholderText(/what are you looking for/i);
    await userEvent.type(textarea, "ASUS laptop");
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    expect(onSend).toHaveBeenCalledWith("ASUS laptop", undefined);
    expect(textarea).toHaveValue("");
  });

  it("calls onSend on Enter key (without Shift)", async () => {
    const onSend = jest.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByPlaceholderText(/what are you looking for/i);
    await userEvent.type(textarea, "laptop");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledWith("laptop", undefined);
  });

  it("does NOT call onSend on Shift+Enter", async () => {
    const onSend = jest.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByPlaceholderText(/what are you looking for/i);
    await userEvent.type(textarea, "laptop");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("all controls are disabled when disabled prop is true", () => {
    render(<ChatInput onSend={jest.fn()} disabled />);
    expect(screen.getByPlaceholderText(/what are you looking for/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /attach image/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /send message/i })).toBeDisabled();
  });

  it("compresses image and shows preview on file selection", async () => {
    jest.mocked(imageCompressor.compressImage).mockResolvedValue("compressed-base64");
    render(<ChatInput onSend={jest.fn()} />);

    const file = new File(["bytes"], "photo.jpg", { type: "image/jpeg" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);

    await waitFor(() => {
      expect(imageCompressor.compressImage).toHaveBeenCalledWith(file);
      expect(screen.getByAltText("Preview")).toBeInTheDocument();
    });
  });

  it("includes compressed image base64 when sending", async () => {
    jest.mocked(imageCompressor.compressImage).mockResolvedValue("compressed-base64");
    const onSend = jest.fn();
    render(<ChatInput onSend={onSend} />);

    const file = new File(["bytes"], "photo.jpg", { type: "image/jpeg" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, file);

    await waitFor(() => screen.getByAltText("Preview"));

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "laptop like this"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    expect(onSend).toHaveBeenCalledWith("laptop like this", "compressed-base64");
  });

  it("removes image preview on X click and clears base64", async () => {
    jest.mocked(imageCompressor.compressImage).mockResolvedValue("compressed-base64");
    render(<ChatInput onSend={jest.fn()} />);

    const file = new File(["bytes"], "photo.jpg", { type: "image/jpeg" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, file);
    await waitFor(() => screen.getByAltText("Preview"));

    fireEvent.click(screen.getByRole("button", { name: /remove image/i }));
    expect(screen.queryByAltText("Preview")).not.toBeInTheDocument();
  });

  it("send is enabled when only an image is attached (no text)", async () => {
    jest.mocked(imageCompressor.compressImage).mockResolvedValue("compressed-base64");
    render(<ChatInput onSend={jest.fn()} />);

    const file = new File(["bytes"], "photo.jpg", { type: "image/jpeg" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /send message/i })).not.toBeDisabled();
    });
  });
});
