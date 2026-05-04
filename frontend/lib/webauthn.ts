"use client";

import {
  startRegistration,
  startAuthentication,
} from "@simplewebauthn/browser";
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";

export async function enrollPasskey(
  options: PublicKeyCredentialCreationOptionsJSON
) {
  return startRegistration({ optionsJSON: options });
}

export async function authenticatePasskey(
  options: PublicKeyCredentialRequestOptionsJSON
) {
  return startAuthentication({ optionsJSON: options });
}
