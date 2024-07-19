import json as _json
import os as _os
import base64 as _base64
import requests as _requests
import pandas as _pandas
import sqlite3 as _sqlite3
from typing import Dict, Optional, Any


class JinkoAPI:
    def __init__(
            self,
            project_id: str,
            api_key: str,
            base_url: Optional[str] = None,
    ):
        """
        Initializes the JinkoAPI class with authentication details.

        Args:
            project_id (str): Project ID for authentication.
            api_key (str): API Key for authentication.
            base_url (str, optional): Base URL for API requests. Defaults to None.
        """
        self._base_url = base_url or _os.environ.get("JINKO_BASE_URL", "https://api.jinko.ai")
        self._project_id = project_id
        self._api_key = api_key

        if not self._api_key.strip():
            raise ValueError("API key cannot be empty")

        if not self._project_id.strip():
            raise ValueError("Project ID cannot be empty")

        # Check if authentication is successful
        if not self.check_authentication():
            raise RuntimeError(f"Authentication failed for Project ID: {self._project_id}")
        print("Authentication successful")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "X-jinko-project-id": self._project_id,
            "Authorization": f"ApiKey {self._api_key}"
        }
        print("Request headers:", headers)  # Debug: Print headers
        return headers

    def encode_custom_headers(self, custom_headers_raw: Dict[str, str]) -> Dict[str, str]:
        """
        Encodes and prepares custom headers for the Jinko API.

        Args:
            custom_headers_raw (dict): Dictionary containing 'description', 'folder_id', 'name', 'version_name'.

        Returns:
            dict: Dictionary containing encoded and formatted headers.
        """
        headers_map = {
            "name": "X-jinko-project-item-name",
            "description": "X-jinko-project-item-description",
            "folder_id": "X-jinko-project-item-folder-ids",
            "version_name": "X-jinko-project-item-version-name",
        }
        headers = {}
        for key, header_name in headers_map.items():
            if key in custom_headers_raw:
                value = custom_headers_raw[key]
                if key == "folder_id":
                    value = _json.dumps([{"id": value, "action": "add"}])
                headers[header_name] = _base64.b64encode(value.encode("utf-8")).decode("utf-8")
        return headers

    def make_url(self, path: str) -> str:
        url = self._base_url + path
        print("Request URL:", url)  # Debug: Print request URL
        return url

    def make_request(
            self,
            path: str,
            method: str = "GET",
            json: Optional[Any] = None,
            csv_data: Optional[str] = None,
            custom_headers: Optional[Dict[str, str]] = None
    ) -> _requests.Response:
        headers = self._get_headers()
        if csv_data:
            headers["Content-Type"] = "text/csv"
        if custom_headers:
            encoded_custom_headers = self.encode_custom_headers(custom_headers)
            headers.update(encoded_custom_headers)

        data_param = "json" if json else "data" if csv_data else None
        data = json or csv_data

        try:
            response = _requests.request(
                method,
                self.make_url(path),
                headers=headers,
                **({data_param: data} if data_param else {})
            )
            response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)
            return response
        except _requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            raise

    def check_authentication(self) -> bool:
        """
        Checks if the authentication is valid.

        Returns:
            bool: Whether the authentication was successful.
        """
        try:
            response = _requests.get(self.make_url("/app/v1/auth/check"), headers=self._get_headers())
            print("Authentication response status code:", response.status_code)  # Debug: Print response status code
            response.raise_for_status()
            try:
                response_json = response.json()
                print("Authentication response JSON:", response_json)  # Debug: Print response JSON
            except _json.JSONDecodeError:
                print("Response content is not valid JSON.")
                print(response.text)
                return False
            return True
        except _requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return False

    def get_project_item(self, short_id: str, revision: Optional[int] = None) -> Dict:
        """
        Retrieves a ProjectItem by its short ID and optionally its revision number.

        Args:
            short_id (str): Short ID of the ProjectItem.
            revision (int, optional): Revision number. Defaults to None.

        Returns:
            dict: ProjectItem data.
        """
        url = f"/app/v1/project-item/{short_id}"
        if revision:
            url += f"?revision={revision}"
        response = self.make_request(url)
        return response.json() if response else {}

    def get_core_item_id(self, short_id: str, revision: Optional[int] = None) -> str:
        """
        Retrieves the CoreItemId for a given ProjectItem.

        Args:
            short_id (str): Short ID of the ProjectItem.
            revision (int, optional): Revision number. Defaults to None.

        Returns:
            str: CoreItemId.
        """
        item = self.get_project_item(short_id, revision)
        core_id = item.get("coreId")
        if not core_id:
            raise ValueError(f"ProjectItem '{short_id}' has no CoreItemId")
        return core_id

    def data_table_to_sqlite(self, data_table_file_path: str) -> str:
        """
        Converts a CSV file to an SQLite database and encodes it in base64.

        Args:
            data_table_file_path (str): Path to the CSV file.

        Returns:
            str: Base64 encoded SQLite database.
        """
        df = _pandas.read_csv(data_table_file_path)
        column_names = df.columns.tolist()

        sqlite_file_path = _os.path.splitext(data_table_file_path)[0] + ".sqlite"
        with _sqlite3.connect(sqlite_file_path) as conn:
            df.to_sql("data", conn, if_exists="replace", index=False, dtype={col: "TEXT" for col in df.columns})
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS data_columns (
                    name TEXT UNIQUE,
                    realname TEXT UNIQUE
                )
            """)
            for name in column_names:
                cursor.execute("INSERT OR IGNORE INTO data_columns (name, realname) VALUES (?, ?)", (name, name))
            conn.commit()

        with open(sqlite_file_path, "rb") as f:
            encoded_data_table = _base64.b64encode(f.read()).decode("utf-8")

        return encoded_data_table

    def get_project_item_url_by_core_item_id(self, core_item_id: str) -> str:
        """
        Retrieves the URL of a ProjectItem based on its CoreItemId.

        Args:
            core_item_id (str): The CoreItemId of the ProjectItem.

        Returns:
            str: The URL of the ProjectItem.
        """
        response = self.make_request(f"/app/v1/core-item/{core_item_id}")
        response_json = response.json() if response else {}
        sid = response_json.get("sid")
        return f"https://jinko.ai/{sid}" if sid else ""


def main():
    config_file_path = "config.json"
    with open(config_file_path, "r") as f:
        config = _json.load(f)

    project_id = config.get("project_id")
    api_key = config.get("api_key")

    try:
        # Initialize JinkoAPI with values from configuration file
        jinko_api = JinkoAPI(project_id=project_id, api_key=api_key)

        # Define folder ID and resource paths
        folder_id = "bdeca5ca-cfe8-4225-a37c-170256403573"
        resources_dir = _os.path.normpath("resources/run_a_trial")
        model_file = _os.path.join(resources_dir, "computational_model.json")
        solving_options_file = _os.path.join(resources_dir, "solving_options.json")
        vpop_file = _os.path.join(resources_dir, "vpop.csv")
        protocol_file = _os.path.join(resources_dir, "protocol.json")
        data_table_file = _os.path.join(resources_dir, "data_table.csv")

        # Step 1: Post a Computational Model
        with open(model_file, "r") as f:
            model = _json.load(f)
        with open(solving_options_file, "r") as f:
            solving_options = _json.load(f)

        response = jinko_api.make_request(
            path="/core/v2/model_manager/jinko_model",
            method="POST",
            json={"model": model, "solvingOptions": solving_options},
        )

        response_json = response.json()
        model_core_item_id = response_json.get("coreItemId")
        model_snapshot_id = response_json.get("snapshotId")

        # Step 2: Create a Vpop Design
        response = jinko_api.make_request(
            path=f"/core/v2/model_manager/jinko_model/{model_core_item_id}/snapshots/{model_snapshot_id}/baseline_descriptors",
        )
        response_json = response.json()
        numeric_descriptors = response_json["numericDescriptors"]

        default_marginal_distributions = [
            {
                "distribution": {
                    "highBound": descriptor["distribution"]["highBound"],
                    "lowBound": descriptor["distribution"]["lowBound"],
                    "tag": descriptor["distribution"]["tag"],
                },
                "id": descriptor["id"],
            }
            for descriptor in numeric_descriptors
            if any(
                tag in descriptor["inputTag"]
                for tag in [
                    "PatientDescriptorKnown",
                    "PatientDescriptorUnknown",
                    "PatientDescriptorPartiallyKnown",
                ]
            )
        ]

        distribution_settings = {
            "initialTumorBurden": {"mean": 1.8, "stdev": 0.08, "base": 10, "tag": "LogNormal"},
            "kccCancerCell": {"mean": 12, "stdev": 0.5, "base": 10, "tag": "LogNormal"},
            "kGrowthCancerCell": {"mean": -3, "stdev": 0.05, "base": 10, "tag": "LogNormal"},
            "vmaxCancerCellDeath": {"mean": -1, "stdev": 0.05, "base": 10, "tag": "LogNormal"},
            "ec50Drug": {"mean": -3.5, "stdev": 0.05, "base": 10, "tag": "LogNormal"},
        }

        updated_marginal_distributions = [
            {
                "id": element["id"],
                "distribution": distribution_settings.get(
                    element["id"],
                    element["distribution"],
                ),
            }
            for element in default_marginal_distributions
        ]

        response = jinko_api.make_request(
            path="/core/v2/vpop_manager/vpop_generator",
            method="POST",
            json={
                "contents": {
                    "computationalModelId": {
                        "coreItemId": model_core_item_id,
                        "snapshotId": model_snapshot_id,
                    },
                    "correlations": [],
                    "marginalCategoricals": [],
                    "marginalDistributions": updated_marginal_distributions,
                },
                "tag": "VpopGeneratorFromDesign",
            },
            custom_headers={
                "name": "vpop design for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        vpop_generator_core_item_id = response_json.get("coreItemId")
        vpop_generator_snapshot_id = response_json.get("snapshotId")

        # Step 3: Generate a Vpop from the Vpop design
        response = jinko_api.make_request(
            path=f"/core/v2/vpop_manager/vpop_generator/{vpop_generator_core_item_id}/snapshots/{vpop_generator_snapshot_id}/vpop",
            method="POST",
            json={
                "contents": {
                    "computationalModelId": {
                        "coreItemId": model_core_item_id,
                        "snapshotId": model_snapshot_id,
                    },
                    "size": 10,
                },
                "tag": "VpopGeneratorOptionsForVpopDesign",
            },
            custom_headers={
                "name": "vpop for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        vpop_core_item_id = response_json["coreItemId"]
        vpop_snapshot_id = response_json["snapshotId"]

        # Step 3 bis: Post a CSV Vpop (optional)
        with open(vpop_file, "r") as file:
            vpop = file.read()

        response = jinko_api.make_request(
            path="/core/v2/vpop_manager/vpop",
            method="POST",
            csv_data=vpop,
            custom_headers={
                "name": "vpop for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        vpop_bis_core_item_id = response_json["coreItemId"]
        vpop_bis_snapshot_id = response_json["snapshotId"]

        # Step 4: Post a Protocol
        with open(protocol_file, "r") as f:
            protocol = _json.load(f)

        response = jinko_api.make_request(
            path="/core/v2/scenario_manager/protocol_design",
            method="POST",
            json=protocol,
            custom_headers={
                "name": "protocol for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        protocol_core_item_id = response_json.get("coreItemId")
        protocol_snapshot_id = response_json.get("snapshotId")

        # Step 5: Post a Data Table
        encoded_data_table = jinko_api.data_table_to_sqlite(data_table_file)

        response = jinko_api.make_request(
            path="/core/v2/data_table_manager/data_table",
            method="POST",
            json={
                "mappings": [],
                "rawData": encoded_data_table,
            },
            custom_headers={
                "name": "data table for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        data_table_core_item_id = response_json.get("coreItemId")
        data_table_snapshot_id = response_json.get("snapshotId")

        # Step 6: Post a Trial
        trial_data = {
            "computationalModelId": {
                "coreItemId": model_core_item_id,
                "snapshotId": model_snapshot_id,
            },
            "protocolDesignId": {
                "coreItemId": protocol_core_item_id,
                "snapshotId": protocol_snapshot_id,
            },
            "vpopId": {"coreItemId": vpop_core_item_id, "snapshotId": vpop_snapshot_id},
            "dataTableDesigns": [
                {
                    "dataTableId": {
                        "coreItemId": data_table_core_item_id,
                        "snapshotId": data_table_snapshot_id,
                    },
                    "options": {
                        "logTransformWideBounds": [],
                        "label": "data_table_simple_tumor",
                    },
                    "include": True,
                }
            ],
        }

        response = jinko_api.make_request(
            path="/core/v2/trial_manager/trial",
            method="POST",
            json=trial_data,
            custom_headers={
                "name": "trial for simple tumor model",
                "folder_id": folder_id,
            },
        )
        response_json = response.json()
        trial_core_item_id = response_json.get("coreItemId")
        trial_snapshot_id = response_json.get("snapshotId")
        trial_id = {"coreItemId": trial_core_item_id, "snapshotId": trial_snapshot_id}

        # Step 7: Run and monitor a trial
        response = jinko_api.make_request(
            path=f"/core/v2/trial_manager/trial/{trial_core_item_id}/snapshots/{trial_snapshot_id}/run",
            method="POST",
        )

        # Step 8: Get trial status
        response = jinko_api.make_request(
            path=f"/core/v2/trial_manager/trial/{trial_core_item_id}/snapshots/{trial_snapshot_id}/status"
        )
        response_json = response.json()
        per_arm_data = response_json.get("perArmSummary", {})

        if response_json.get("isRunning", False):
            print("Job is running.")
        else:
            print("Job succeeded.")

        if per_arm_data:
            per_arm_summary = _pandas.DataFrame.from_dict(per_arm_data, orient="index")
            per_arm_summary.reset_index(inplace=True)
            per_arm_summary.rename(columns={"index": "Arm"}, inplace=True)
            print(per_arm_summary)
        else:
            print("No 'perArmSummary' data found in the response.")

        # Step 9: Visualise trial results
        response = jinko_api.make_request(
            f"/core/v2/trial_manager/trial/{trial_core_item_id}/snapshots/{trial_snapshot_id}/output_ids",
            method="GET",
        )
        response_summary = response.json()  # Corrected this line
        print("Available time series:\n", response_summary, "\n")

        # Step 10: Retrieve and visualize time series data
        ids_for_time_series = ["tumorBurden"]

        try:
            print("Retrieving time series data...")
            response = jinko_api.make_request(
                "/core/v2/result_manager/timeseries_summary",
                method="POST",
                json={
                    "select": ids_for_time_series,
                    "trialId": trial_id,
                },
            )
            if response.status_code == 200:
                print("Time series data retrieved successfully.")
                archive = zipfile.ZipFile(io.BytesIO(response.content))
                filename = archive.namelist()[0]
                print(f"Extracted time series file: {filename}")
                csv_time_series = archive.read(filename).decode("utf-8")

                # Load data into DataFrame
                df_time_series = _pandas.read_csv(io.StringIO(csv_time_series))
                print(df_time_series.head(5))

                # Extract unique patient IDs
                unique_patient_ids = df_time_series["Patient Id"].unique().tolist()
                print("Unique patient IDs:", unique_patient_ids)

                # Filter data for the first patient
                if unique_patient_ids:
                    patient_data = df_time_series[df_time_series["Patient Id"] == unique_patient_ids[0]]

                    # Plot using Plotly
                    fig = px.line(
                        patient_data,
                        x="Time",
                        y="Value",
                        color="Arm",
                        title="Time Series of Tumor Burden",
                        labels={"Time": "Time (seconds)", "Value": "Tumor Burden Value"},
                        markers=True,
                    )
                    fig.show()
                else:
                    print("No patient data found.")

            else:
                print(f"Failed to retrieve time series data: {response.status_code} - {response.reason}")
                response.raise_for_status()
        except Exception as e:
            print(f"Error during time series retrieval or processing: {e}")
            raise

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
