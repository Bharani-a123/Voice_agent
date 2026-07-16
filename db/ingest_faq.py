"""
ingest_faq.py — Ingestion pipeline for Phase 4.
Populates local Qdrant collection with Greenfield Multi-Specialty Clinic FAQ knowledge chunks.
Run: python db/ingest_faq.py
"""

from agent.rag_service import rag

CLINIC_ID = "d72164a7-dd69-45c2-ac65-92c588b303a8"  # matches our pilot clinic seed

FAQ_DATA = """
Clinic Hours and Availability:
Greenfield Multi-Specialty Clinic is open Monday to Saturday, from 8:00 AM to 8:00 PM IST. We are closed on Sundays. Appointments can be booked up to 48 hours in advance.

Accepted Insurance Plans:
We accept most major health insurance plans including Star Health, New India Assurance, HDFC Ergo, and ICICI Lombard. Please bring your valid insurance card at the time of your visit to verify coverage.

Clinic Location and Parking:
We are located at 12 MG Road, Bangalore, Karnataka. Ample parking is available for visitors in the basement of our facility. We are easily accessible via metro (MG Road metro station).

Cardiology Department Doctors:
Our Cardiology department is led by Dr. Priya Sharma and Dr. Arjun Mehta. Both have over 15 years of experience in diagnosing and treating cardiovascular conditions.

Orthopaedics Department Doctors:
Orthopaedics consultations are handled by Dr. Kavitha Rajan. Dr. Rajan specializes in joint replacement surgery, sports medicine, and treating complex fractures.

First Visit Requirements:
For your first visit, please arrive 15 minutes early to complete registration. You must bring a valid government-issued photo ID, your health insurance card, and any recent medical records or test reports.

Emergency Services Disclaimer:
For life-threatening medical emergencies, please call 112 immediately or go to your nearest hospital emergency room. Greenfield Clinic is an outpatient facility and does not provide emergency room services.
"""


def main():
    print("=" * 60)
    print("MediCare Connect — FAQ Knowledge Ingestion (Phase 4)")
    print("=" * 60)
    print(f"Clinic ID: {CLINIC_ID}")
    print("Ingesting FAQ documents into local Qdrant collection...")

    try:
        # Ingest text data
        rag.ingest_faq_text(
            clinic_id=CLINIC_ID,
            source_name="greenfield_faq_doc",
            faq_text=FAQ_DATA
        )
        print("\n[SUCCESS] FAQ ingestion complete! Local vector store updated.")
        print("=" * 60)
    except Exception as e:
        print(f"\n[ERROR] Ingestion failed: {e}")


if __name__ == "__main__":
    main()
