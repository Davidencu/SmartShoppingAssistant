import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RegisterForm from "@/components/auth/RegisterForm";

const mockSignInWithOtp = jest.fn();
const mockRouterPush = jest.fn();

jest.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { signInWithOtp: mockSignInWithOtp },
  }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

const VALID_EMAIL = "ion@example.com";

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText("Ion Popescu"), "Ion Popescu");
  await user.type(screen.getByPlaceholderText("ion@example.com"), VALID_EMAIL);
  await user.type(screen.getByPlaceholderText("+40712345678"), "+40712345678");
  await user.type(screen.getByPlaceholderText("Name on parcel"), "Ion Popescu");
  await user.type(screen.getByPlaceholderText("Strada Victoriei 1"), "Strada Victoriei 1");
  await user.type(screen.getByPlaceholderText("București"), "București");
  await user.type(screen.getByPlaceholderText("010011"), "010011");
}

describe("RegisterForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSignInWithOtp.mockResolvedValue({ data: {}, error: null });
  });

  it("renders all required fields", () => {
    render(<RegisterForm />);
    expect(screen.getByPlaceholderText("ion@example.com")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("+40712345678")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Strada Victoriei 1")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("București")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("010011")).toBeInTheDocument();
  });

  it("shows login link", () => {
    render(<RegisterForm />);
    expect(screen.getByRole("link", { name: /sign in/i })).toBeInTheDocument();
  });

  it("calls signInWithOtp with user metadata on valid submit", async () => {
    render(<RegisterForm />);
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(mockSignInWithOtp).toHaveBeenCalledWith(
        expect.objectContaining({
          email: VALID_EMAIL,
          options: expect.objectContaining({
            shouldCreateUser: true,
            data: expect.objectContaining({
              full_name: "Ion Popescu",
              phone: "+40712345678",
            }),
          }),
        })
      );
    });
  });

  it("redirects to /verify after successful OTP send", async () => {
    render(<RegisterForm />);
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith(
        expect.stringContaining(`/verify?email=${encodeURIComponent(VALID_EMAIL)}`)
      );
    });
  });

  it("shows error when Supabase returns an error", async () => {
    mockSignInWithOtp.mockResolvedValue({
      data: {},
      error: new Error("Signup is disabled"),
    });

    render(<RegisterForm />);
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/signup is disabled/i)).toBeInTheDocument();
    });
  });
});
