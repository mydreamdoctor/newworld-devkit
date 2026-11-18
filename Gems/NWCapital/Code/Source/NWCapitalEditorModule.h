/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#pragma once

#include <NWCapitalModule.h>

namespace NWCapital
{
    class NWCapitalEditorModule
        : public NWCapitalModule
    {
    public:
        AZ_RTTI(NWCapitalEditorModule, "{9F3C5B7D-2E6A-4F8B-A4D1-7E9F3B5C6D06}", NWCapitalModule);

        NWCapitalEditorModule();
        ~NWCapitalEditorModule() override = default;

        AZ::ComponentTypeList GetRequiredSystemComponents() const override;
    };
}
