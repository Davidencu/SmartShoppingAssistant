export interface Address {
  recipient_name: string;
  street: string;
  city: string;
  state?: string;
  country: string;
  zip_code: string;
}

export interface ProfileCreate {
  full_name: string;
  phone: string;
  address: Address;
}

export interface UserProfile {
  id: string;
  full_name: string;
  phone: string;
  created_at: string;
}

export interface UserAddress extends Address {
  id: string;
  user_id: string;
  is_default: boolean;
  created_at: string;
}

export interface ProfileResponse {
  profile: UserProfile;
  address: UserAddress;
}

export type TransactionType = "TOPUP" | "FREEZE" | "DEDUCT" | "REFUND";

export interface Wallet {
  id: string;
  user_id: string;
  balance_cents: number;
  frozen_cents: number;
  available_cents: number;
  currency: string;
  updated_at: string;
}

export interface WalletTransaction {
  id: string;
  wallet_id: string;
  type: TransactionType;
  amount_cents: number;
  reference_id: string | null;
  order_id: string | null;
  created_at: string;
}

export interface WalletResponse {
  wallet: Wallet;
  recent_transactions: WalletTransaction[];
}
