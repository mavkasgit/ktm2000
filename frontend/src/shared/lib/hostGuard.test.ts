import { describe, expect, it } from "vitest";
import { isPrivateHost } from "./hostGuard";

describe("isPrivateHost", () => {
  it("accepts loopback hosts", () => {
    expect(isPrivateHost("http://localhost:5172")).toBe(true);
    expect(isPrivateHost("http://127.0.0.1:8012")).toBe(true);
    expect(isPrivateHost("http://[::1]:5172")).toBe(true);
  });

  it("accepts private-network hosts", () => {
    expect(isPrivateHost("http://10.0.0.5:8020")).toBe(true);
    expect(isPrivateHost("http://172.16.5.2:5172")).toBe(true);
    expect(isPrivateHost("http://192.168.1.10:5172")).toBe(true);
  });

  it("accepts mDNS local hostnames", () => {
    expect(isPrivateHost("http://ktm2000.local:5172")).toBe(true);
  });

  it("accepts scheme-less private hosts", () => {
    expect(isPrivateHost("localhost:5172")).toBe(true);
    expect(isPrivateHost("192.168.1.10:5172")).toBe(true);
    expect(isPrivateHost("10.0.0.5:8020/api")).toBe(true);
  });

  it("rejects public hostnames", () => {
    expect(isPrivateHost("http://example.com")).toBe(false);
    expect(isPrivateHost("https://ktm2000-nginx-prod")).toBe(false);
    expect(isPrivateHost("http://ktm2000.ru")).toBe(false);
  });

  it("rejects public IP addresses", () => {
    expect(isPrivateHost("http://8.8.8.8:443")).toBe(false);
    expect(isPrivateHost("http://194.28.10.5")).toBe(false);
  });
});