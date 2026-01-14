export type LeadValidationInput = {
  name: string;
  phone: string;
  address: string;
  selectedSlot?: string | null;
};

export function isLeadFormComplete({
  name,
  phone,
  address,
  selectedSlot,
}: LeadValidationInput): boolean {
  return (
    name.trim().length > 1 &&
    phone.trim().length >= 7 &&
    address.trim().length > 4 &&
    Boolean(selectedSlot)
  );
}
